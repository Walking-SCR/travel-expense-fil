"""
xlsx_edit.py — Direct xlsx manipulation without openpyxl save.
Copies template → output, modifies sheet XML + sharedStrings.xml in-place.

Preserves ALL template XML structure: calcChain.xml, customXml/,
namespace declarations, phoneticPr, workbook metadata, etc.
"""
import shutil, zipfile, os, re
from datetime import datetime, date
from lxml import etree

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NSMAP = {'s': NS}

# Excel serial date epoch
EXCEL_EPOCH = datetime(1899, 12, 30)


def date_to_serial(d):
    """Convert date to Excel serial number."""
    if isinstance(d, datetime):
        dt = d
    else:
        dt = datetime(d.year, d.month, d.day)
    delta = dt - EXCEL_EPOCH
    return delta.days + (delta.seconds / 86400.0)


def cell_row(ref):
    """Extract row number from cell reference like 'A10' → 10."""
    return int(re.search(r'(\d+)$', ref).group(1))


def cell_col(ref):
    """Extract column letter from cell reference like 'A10' → 'A'."""
    return re.match(r'([A-Z]+)', ref).group(1)


def _shift_ref(ref, offset):
    """Shift row number in a cell reference: 'A10' with offset=-2 → 'A8'."""
    m = re.match(r'^([A-Z]+)(\d+)$', ref)
    if m:
        return f'{m.group(1)}{int(m.group(2)) + offset}'
    return ref


def _shift_formula(formula, offset, start_row):
    """Shift row numbers in a formula for rows >= start_row."""
    def _repl(m):
        col = m.group(1)
        r = int(m.group(2))
        if r >= start_row:
            return f'{col}{r + offset}'
        return m.group(0)
    return re.sub(r'([A-Z]{1,3})(\d+)', _repl, formula)


class XlsxEditor:
    """Edit xlsx files by directly modifying XML within the zip archive.

    Usage:
        ed = XlsxEditor(template_path, output_path)
        ed.load()
        ed.set_cell_text(2, 'C2', '姓名')
        ed.set_cell_number(2, 'F10', 123.45)
        ed.set_cell_formula(2, 'L10', 'SUM(F10:K10)')
        ed.flush()
    """

    def __init__(self, template_path, output_path):
        shutil.copy(template_path, output_path)
        self._path = output_path
        self._cache = {}   # filename → bytes
        self._ss_list = []  # list of (raw_xml_string_or_None, as_text) for shared strings
        self._ss_loaded = False
        self._dirty = set()

    # ── zip read/write ──────────────────────────────────────────────

    def load(self):
        """Read all files from zip into memory cache."""
        with zipfile.ZipFile(self._path, 'r') as z:
            for name in z.namelist():
                self._cache[name] = z.read(name)
        return self

    def flush(self):
        """Write all cached changes back to zip."""
        tmp = self._path + '.tmp'
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for name in sorted(self._cache.keys()):
                zout.writestr(name, self._cache[name])
        os.replace(tmp, self._path)

    def _get_xml(self, filename):
        """Read cached file as string (decoded)."""
        return self._cache[filename].decode('utf-8')

    def _set_xml(self, filename, xml):
        """Update cached file from string."""
        self._cache[filename] = xml.encode('utf-8')
        self._dirty.add(filename)

    def _sheet_path(self, sheet_index):
        """Get path for sheet by 1-based index."""
        return f'xl/worksheets/sheet{sheet_index}.xml'

    def _get_sheet(self, sheet_index):
        return self._get_xml(self._sheet_path(sheet_index))

    def _set_sheet(self, sheet_index, xml):
        self._set_xml(self._sheet_path(sheet_index), xml)

    # ── Shared Strings ─────────────────────────────────────────────

    def _load_ss(self):
        """Parse sharedStrings.xml into _ss_list."""
        if self._ss_loaded:
            return
        self._ss_list = []
        raw = self._cache.get('xl/sharedStrings.xml')
        if not raw:
            return
        root = etree.fromstring(raw)
        for si in root.findall('s:si', NSMAP):
            # Get full text content (including rich text runs)
            texts = []
            for t in si.iter(f'{{{NS}}}t'):
                if t.text:
                    texts.append(t.text)
            text = ''.join(texts)
            # Store as (raw_xml_string, plain_text)
            xml_str = etree.tostring(si, encoding='unicode')
            self._ss_list.append((xml_str, text))
        self._ss_loaded = True

    def get_shared_strings(self):
        """Return list of plain text of all shared strings."""
        self._load_ss()
        return [t for _, t in self._ss_list]

    def add_shared_string(self, text):
        """Add a plain text shared string, return its index."""
        self._load_ss()
        idx = len(self._ss_list)
        # Build a simple <si><t>text</t></si>
        escaped = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # Escape newlines, carriage returns, tabs
        escaped = escaped.replace('\r\n', '&#10;').replace('\r', '&#10;').replace('\n', '&#10;')
        # Check if text needs xml:space="preserve"
        preserve = ' xml:space="preserve"' if (text and (text[0] == ' ' or text[-1] == ' ' or text.strip() == '')) else ''
        si_xml = f'<si><t{preserve}>{escaped}</t></si>'
        self._ss_list.append((si_xml, text))
        self._dirty.add('xl/sharedStrings.xml')
        return idx

    def _save_ss(self):
        """Write shared strings back to XML."""
        if 'xl/sharedStrings.xml' not in self._dirty and self._ss_loaded:
            # Check if any strings were added by comparing lengths
            raw = self._cache.get('xl/sharedStrings.xml', b'')
            root = etree.fromstring(raw)
            existing_count = len(root.findall('s:si', NSMAP))
            if len(self._ss_list) == existing_count:
                return  # No changes
        # Always rebuild if _ss_list was modified
        total = len(self._ss_list)
        # Build tree manually
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<sst xmlns="{NS}" count="{total}" uniqueCount="{total}">',
        ]
        for si_xml, _ in self._ss_list:
            lines.append(si_xml)
        lines.append('</sst>')
        self._cache['xl/sharedStrings.xml'] = '\n'.join(lines).encode('utf-8')

    # ── Cell Manipulation ───────────────────────────────────────────

    def _set_cell_inner(self, sheet_xml, cell_ref, inner_xml, force_attrs=''):
        """Replace the content of a cell element in sheet XML.

        Handles both <c .../> and <c ...>...</c> forms.
        Preserves the 's' (style) attribute.
        """
        # Pattern 1: <c r="CELL" ...>...</c> (expanded form - NOT self-closing)
        pat1 = rf'(<c\s+r="{re.escape(cell_ref)}")([^>/]*)>.*?</c>'
        m = re.search(pat1, sheet_xml, re.DOTALL)
        if m:
            tag_start = m.group(1)
            attrs = m.group(2)
            # Remove existing t= if present
            attrs = re.sub(r'\s+t="[^"]*"', '', attrs)
            new = f'{tag_start}{attrs}{force_attrs}>{inner_xml}</c>'
            return sheet_xml[:m.start()] + new + sheet_xml[m.end():]

        # Pattern 2: <c r="CELL" .../> (self-closing)
        pat2 = rf'(<c\s+r="{re.escape(cell_ref)}")([^>]*)/>'
        m = re.search(pat2, sheet_xml)
        if m:
            tag_start = m.group(1)
            attrs = m.group(2).rstrip('/')
            new = f'{tag_start}{attrs}{force_attrs}>{inner_xml}</c>'
            return sheet_xml[:m.start()] + new + sheet_xml[m.end():]

        # Cell not found — return unchanged
        return sheet_xml

    def set_cell_text(self, sheet_index, cell_ref, text):
        """Set cell to a text value (via shared string)."""
        ss_idx = self.add_shared_string(text)
        sheet_xml = self._get_sheet(sheet_index)
        inner = f'<v>{ss_idx}</v>'
        new_xml = self._set_cell_inner(sheet_xml, cell_ref, inner, force_attrs=' t="s"')
        self._set_sheet(sheet_index, new_xml)

    def set_cell_number(self, sheet_index, cell_ref, value):
        """Set cell to a number value."""
        sheet_xml = self._get_sheet(sheet_index)
        if isinstance(value, float) and value == int(value):
            val_str = str(int(value))
        else:
            val_str = str(value)
        new_xml = self._set_cell_inner(sheet_xml, cell_ref, f'<v>{val_str}</v>')
        self._set_sheet(sheet_index, new_xml)

    def set_cell_formula(self, sheet_index, cell_ref, formula):
        """Set cell to a formula (no cached value)."""
        # Strip leading '=' if present; Excel stores formulas without it in <f>
        formula = formula.lstrip('=')
        sheet_xml = self._get_sheet(sheet_index)
        new_xml = self._set_cell_inner(sheet_xml, cell_ref, f'<f>{formula}</f>')
        self._set_sheet(sheet_index, new_xml)

    def set_cell_date(self, sheet_index, cell_ref, d):
        """Set cell to a date value (Excel serial number)."""
        serial = int(date_to_serial(d))
        self.set_cell_number(sheet_index, cell_ref, serial)

    def clear_cell(self, sheet_index, cell_ref):
        """Clear a cell's value, keep its style."""
        sheet_xml = self._get_sheet(sheet_index)
        # Full form with content
        pat1 = rf'(<c\s+r="{re.escape(cell_ref)}")([^>/]*)>.*?</c>'
        m = re.search(pat1, sheet_xml, re.DOTALL)
        if m:
            attrs = m.group(2)
            # Remove t="s"
            attrs = re.sub(r'\s+t="[^"]*"', '', attrs)
            new = f'<c r="{cell_ref}"{attrs}/>'
            return self._set_sheet(sheet_index, sheet_xml[:m.start()] + new + sheet_xml[m.end():])
        # Already self-closing — nothing to clear
        return sheet_xml

    def clear_row_cells(self, sheet_index, row, col_letters):
        """Clear specific column cells in a row."""
        for col in col_letters:
            self.clear_cell(sheet_index, f'{col}{row}')

    # ── Row Operations ──────────────────────────────────────────────

    def clear_rows(self, sheet_index, start_row, end_row, col_letters=None):
        """Clear cell values in row range.

        If col_letters is None, clears all cells found in each row.
        """
        sheet_xml = self._get_sheet(sheet_index)
        if col_letters:
            cols_to_clear = col_letters
        else:
            cols_to_clear = None

        for r in range(start_row, end_row + 1):
            if cols_to_clear:
                for col in cols_to_clear:
                    ref = f'{col}{r}'
                    sheet_xml = self._clear_cell_ref(sheet_xml, ref)
            else:
                # Find all cells in this row and clear them
                pat = rf'<c\s+r="([A-Z]+){re.escape(str(r))}"([^>/]*)>.*?</c>'
                def _clr(m, row=r):
                    attrs = re.sub(r'\s+t="[^"]*"', '', m.group(2))
                    return f'<c r="{m.group(1)}{row}"{attrs}/>'
                sheet_xml = re.sub(pat, _clr, sheet_xml)

        self._set_sheet(sheet_index, sheet_xml)

    def _clear_cell_ref(self, sheet_xml, ref):
        """Clear a single cell by reference, return modified XML."""
        pat1 = rf'(<c\s+r="{re.escape(ref)}")([^>/]*)>.*?</c>'
        m = re.search(pat1, sheet_xml, re.DOTALL)
        if m:
            attrs = re.sub(r'\s+t="[^"]*"', '', m.group(2))
            return sheet_xml[:m.start()] + f'<c r="{ref}"{attrs}/>' + sheet_xml[m.end():]
        return sheet_xml

    def delete_rows(self, sheet_index, start_row, count):
        """Delete rows from sheet XML, renumbering everything below."""
        if count <= 0:
            return
        sheet_xml = self._get_sheet(sheet_index)

        # 1. Remove row elements for deleted rows
        for r in range(start_row, start_row + count):
            pat = rf'<row\s+r="{r}"[^>]*>.*?</row>'
            sheet_xml = re.sub(pat, '', sheet_xml, flags=re.DOTALL)
            pat2 = rf'<row\s+r="{r}"[^>]*/>'
            sheet_xml = re.sub(pat2, '', sheet_xml)
            # Remove orphaned newlines
            sheet_xml = re.sub(r'\n\s*\n', '\n', sheet_xml)

        # 2. Renumber rows, cells, formulas, and merge refs below deleted range
        offset = -count
        first_affected = start_row + count  # first row that shifts

        # Renumber <row r="N"> elements
        def _renumber_row(m):
            r = int(m.group(1))
            if r >= first_affected:
                return str(r + offset)
            return m.group(0)
        sheet_xml = re.sub(r'(?<=<row r=")(\d+)(?=")', _renumber_row, sheet_xml)

        # Renumber cell references: <c r="A12"> → <c r="A10">
        # Only renumber cells that are BELOW the deleted range
        def _renumber_cell(m):
            col = m.group(1)
            r = int(m.group(2))
            if r >= first_affected:
                return f'{col}{r + offset}'
            return m.group(0)
        sheet_xml = re.sub(r'(?<![A-Z])([A-Z]+)(\d+)', _renumber_cell, sheet_xml)

        # Renumber merge cells
        def _renumber_merge(m):
            ref = m.group(1)
            parts = ref.split(':')
            new_parts = []
            for p in parts:
                col = re.match(r'([A-Z]+)', p).group(1)
                row_num = int(re.search(r'(\d+)', p).group(1))
                if row_num >= first_affected:
                    new_parts.append(f'{col}{row_num + offset}')
                else:
                    new_parts.append(p)
            return f'<mergeCell ref="{":".join(new_parts)}"/>'
        sheet_xml = re.sub(r'<mergeCell ref="([^"]+)"/>', _renumber_merge, sheet_xml)

        # Renumber formulas: shift row numbers in all <f> elements
        def _renumber_formula(m):
            attrs = m.group(1)
            formula = m.group(2)
            shifted = _shift_formula(formula, offset, first_affected)
            return f'<f{attrs}>{shifted}</f>'
        sheet_xml = re.sub(r'<f([^>]*)>(.*?)</f>', _renumber_formula, sheet_xml)

        self._set_sheet(sheet_index, sheet_xml)

    # ── Merge Cells ─────────────────────────────────────────────────

    def merge_cells(self, sheet_index, range_str):
        """Add a merge cell reference if not already present."""
        sheet_xml = self._get_sheet(sheet_index)
        if range_str in sheet_xml:
            return  # Already exists
        mc = re.search(r'(<mergeCells[^>]*>)(.*?)(</mergeCells>)', sheet_xml, re.DOTALL)
        if mc:
            start_tag = mc.group(1)
            existing = mc.group(2)
            end_tag = mc.group(3)
            # Count existing merges
            current_count = existing.count('<mergeCell')
            new_count = current_count + 1
            # Update count attribute
            start_tag = re.sub(r'count="\d+"', f'count="{new_count}"', start_tag)
            new_merge = f'\n<mergeCell ref="{range_str}"/>'
            new_xml = start_tag + existing + new_merge + end_tag
            sheet_xml = sheet_xml[:mc.start()] + new_xml + sheet_xml[mc.end():]
            self._set_sheet(sheet_index, sheet_xml)

    def unmerge_cells(self, sheet_index, range_str):
        """Remove a merge cell reference if present."""
        sheet_xml = self._get_sheet(sheet_index)
        pat = re.escape(range_str)
        sheet_xml = re.sub(rf'\s*<mergeCell ref="{pat}"/>', '', sheet_xml)
        # Update count
        mc = re.search(r'<mergeCells\s+count="(\d+)"', sheet_xml)
        if mc:
            current = int(mc.group(1))
            if current > 0:
                sheet_xml = sheet_xml.replace(
                    f'count="{current}"', f'count="{current - 1}"', 1)
        self._set_sheet(sheet_index, sheet_xml)

    # ── Alignment ───────────────────────────────────────────────────

    def set_cell_wrap(self, sheet_index, cell_ref):
        """Set cell to wrap text (adds alignment wrapText="1")."""
        sheet_xml = self._get_sheet(sheet_index)

        # If cell has a style (s="N") whose xf has applyAlignment="1",
        # the style's alignment overrides inline — patch the xf to include wrapText.
        m_style = re.search(rf'<c\s+r="{re.escape(cell_ref)}"\s+s="(\d+)"', sheet_xml)
        if m_style:
            self._ensure_xf_wrap(int(m_style.group(1)))

        # Pattern 1: expanded form <c ...>content</c>
        pat = rf'(<c\s+r="{re.escape(cell_ref)}"[^>]*>)(.*?)</c>'
        m = re.search(pat, sheet_xml, re.DOTALL)
        if m:
            tag_start = m.group(1)
            inner = m.group(2)
            if '<alignment' in inner:
                if 'wrapText="1"' in inner:
                    return
                inner = re.sub(r'(<alignment[^>]*?)\s*/?>', r'\1 wrapText="1"/>', inner)
            else:
                inner += '<alignment wrapText="1" vertical="center"/>'
            new_xml = sheet_xml[:m.start()] + tag_start + inner + '</c>' + sheet_xml[m.end():]
            self._set_sheet(sheet_index, new_xml)
            return

        # Pattern 2: self-closing <c .../>
        pat2 = rf'(<c\s+r="{re.escape(cell_ref)}"[^>]*)/>'
        m2 = re.search(pat2, sheet_xml)
        if m2:
            new_xml = (sheet_xml[:m2.start()] + m2.group(1) +
                       '><alignment wrapText="1" vertical="center"/></c>' +
                       sheet_xml[m2.end():])
            self._set_sheet(sheet_index, new_xml)

    def _ensure_xf_wrap(self, xf_id):
        """Patch styles.xml so xf[xf_id] alignment includes wrapText="1".

        When a cell style (xf) has applyAlignment="1", its alignment overrides
        any inline cell alignment.  We add wrapText to the style's alignment
        so the style itself carries wrapText.
        """
        if not hasattr(self, '_xf_wrap_patched'):
            self._xf_wrap_patched = set()
        if xf_id in self._xf_wrap_patched:
            return

        styles_path = 'xl/styles.xml'
        styles_xml = self._get_xml(styles_path)

        # Locate cellXfs and find the xf_id-th xf child
        cellxfs_m = re.search(r'<cellXfs[^>]*>', styles_xml)
        if not cellxfs_m:
            return
        after = styles_xml[cellxfs_m.end():]
        count = 0
        xf_start = xf_end = None
        for xfm in re.finditer(r'<xf\s[^>]*/>|<xf\s[^>]*>.*?</xf>', after, re.DOTALL):
            if count == xf_id:
                xf_start = cellxfs_m.end() + xfm.start()
                xf_end = cellxfs_m.end() + xfm.end()
                break
            count += 1
        if xf_start is None:
            return

        xf_full = styles_xml[xf_start:xf_end]
        if 'wrapText' in xf_full:
            self._xf_wrap_patched.add(xf_id)
            return
        if '<alignment' not in xf_full:
            return

        new_xf = xf_full.replace('<alignment', '<alignment wrapText="1"')
        styles_xml = styles_xml[:xf_start] + new_xf + styles_xml[xf_end:]
        self._set_xml(styles_path, styles_xml)
        self._xf_wrap_patched.add(xf_id)

    def set_row_auto_height(self, sheet_index, row):
        """Remove fixed height from a row so Excel auto-adjusts to fit wrapped text."""
        sheet_xml = self._get_sheet(sheet_index)
        # Find the row element opening tag
        m = re.search(rf'(<row\s+r="{row}"[^>]*?)>', sheet_xml)
        if not m:
            return
        tag = m.group(1)
        # strip customHeight and ht attributes (any order)
        tag2 = re.sub(r'\s+customHeight="[^"]*"', '', tag)
        tag2 = re.sub(r'\s+ht="[^"]*"', '', tag2)
        if tag2 != tag:
            sheet_xml = sheet_xml[:m.start(1)] + tag2 + '>' + sheet_xml[m.end():]
            self._set_sheet(sheet_index, sheet_xml)

    # ── High-level helpers ──────────────────────────────────────────

    def fill_header_text(self, sheet_index, mapping):
        """Fill multiple header cells with text values.

        mapping: dict of {cell_ref: text}
        """
        for ref, text in mapping.items():
            self.set_cell_text(sheet_index, ref, text)

    def strip_calc_chain(self):
        """Remove calcChain.xml and its references from the output.

        Call before flush() when formulas have been rewritten,
        since stale calcChain entries would trigger Excel warnings.
        """
        self._cache.pop('xl/calcChain.xml', None)
        # Remove reference from workbook.xml.rels
        rels_path = 'xl/_rels/workbook.xml.rels'
        rels = self._cache.get(rels_path)
        if rels:
            rels_str = rels.decode('utf-8')
            rels_str = re.sub(
                r'\s*<Relationship\s+[^>]*calcChain\.xml[^>]*/>',
                '', rels_str
            )
            self._cache[rels_path] = rels_str.encode('utf-8')
            self._dirty.add(rels_path)

    def flush_all(self):
        """Write all pending changes to zip."""
        if self._ss_loaded:
            self._save_ss()
        self.flush()
