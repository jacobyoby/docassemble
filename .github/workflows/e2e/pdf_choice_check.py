"""Integration regression for editable choice fields in ``fill_template``.

The harness creates its own two-page AcroForm and loads the candidate module
from ``--module``.  It never copies over the installed docassemble runtime.

Examples (run with the docassemble image's Python):

    pdf_choice_check.py expect-fail --module /tmp/stock/pdftk.py
    pdf_choice_check.py expect-pass --module /tmp/candidate/pdftk.py
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pikepdf

PAIR_OPTIONS = [("00", " "), ("02", "Bergen"), ("03", "Burlington")]
DIRECT_OPTIONS = [("d0", "Alpha"), ("d2", "Delta")]
STRING_OPTIONS = ["A", "B"]
CHOICE_NAMES = ("choice", "direct", "strings", "noopt", "note")


def load_candidate(module_path: str | None):
    """Load one candidate file without replacing the installed runtime."""

    if module_path is None:
        from docassemble.base import pdftk

        return pdftk
    path = Path(module_path).expanduser().resolve()
    if not path.is_file():
        raise AssertionError(f"candidate module does not exist: {path}")
    spec = importlib.util.spec_from_file_location("pdf_choice_candidate", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load candidate module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _appearance(pdf: pikepdf.Pdf, resources: pikepdf.Object) -> pikepdf.Object:
    return pdf.make_stream(
        b"q BT /Helv 10 Tf 2 10 Td (old) Tj ET Q",
        {
            "/Type": pikepdf.Name("/XObject"),
            "/Subtype": pikepdf.Name("/Form"),
            "/FormType": 1,
            "/BBox": pikepdf.Array([0, 0, 180, 24]),
            "/Resources": resources,
        },
    )


def _opt_pairs(options: list[tuple[str, str]]) -> pikepdf.Array:
    return pikepdf.Array(
        [pikepdf.Array([pikepdf.String(export), pikepdf.String(display)]) for export, display in options]
    )


def _widget(
    pdf: pikepdf.Pdf,
    page: pikepdf.Page,
    rect: list[int],
    resources: pikepdf.Object,
    parent: pikepdf.Object | None = None,
    field_type: str | None = None,
    name: str | None = None,
    options: pikepdf.Array | None = None,
) -> pikepdf.Object:
    values: dict[str, object] = {
        "/Type": pikepdf.Name("/Annot"),
        "/Subtype": pikepdf.Name("/Widget"),
        "/Rect": pikepdf.Array(rect),
        "/P": page.obj,
        "/AP": pikepdf.Dictionary({"/N": _appearance(pdf, resources)}),
    }
    if parent is not None:
        values["/Parent"] = parent
    if field_type is not None:
        values["/FT"] = pikepdf.Name(field_type)
        if field_type == "/Ch":
            values["/Ff"] = 1 << 17
    if name is not None:
        values["/T"] = pikepdf.String(name)
    if options is not None:
        values["/Opt"] = options
    return pdf.make_indirect(pikepdf.Dictionary(values))


def _parent_field(
    pdf: pikepdf.Pdf,
    name: str,
    field_type: str,
    resources: pikepdf.Object,
    options: pikepdf.Array | None = None,
) -> pikepdf.Object:
    values: dict[str, object] = {
        "/FT": pikepdf.Name(field_type),
        "/T": pikepdf.String(name),
        "/V": pikepdf.String(""),
        "/DA": pikepdf.String("/Helv 10 Tf 0 g"),
        "/Kids": pikepdf.Array(),
    }
    if field_type == "/Ch":
        values["/Ff"] = 1 << 17
        values["/I"] = pikepdf.Array([0])
    if options is not None:
        values["/Opt"] = options
    return pdf.make_indirect(pikepdf.Dictionary(values))


def build_fixture(path: Path) -> None:
    """Write a small editable form with parent and direct field shapes."""

    pdf = pikepdf.Pdf.new()
    page_one = pdf.add_blank_page(page_size=(612, 792))
    page_two = pdf.add_blank_page(page_size=(612, 792))
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            {"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")}
        )
    )
    resources = pikepdf.Dictionary({"/Font": pikepdf.Dictionary({"/Helv": font})})
    acroform = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/DA": pikepdf.String("/Helv 10 Tf 0 g"),
                "/DR": resources,
                "/Fields": pikepdf.Array(),
                "/NeedAppearances": True,
            }
        )
    )
    pdf.Root.AcroForm = acroform
    page_one.obj.Annots = pikepdf.Array()
    page_two.obj.Annots = pikepdf.Array()

    choice = _parent_field(pdf, "choice", "/Ch", resources, _opt_pairs(PAIR_OPTIONS))
    acroform.Fields.append(choice)
    for page in (page_one, page_two):
        widget = _widget(pdf, page, [72, 700, 252, 724], resources, parent=choice)
        choice.Kids.append(widget)
        page.obj.Annots.append(widget)

    direct = _widget(
        pdf,
        page_one,
        [72, 660, 252, 684],
        resources,
        field_type="/Ch",
        name="direct",
        options=_opt_pairs(DIRECT_OPTIONS),
    )
    direct.I = pikepdf.Array([0])
    direct.V = pikepdf.String("")
    direct.DA = pikepdf.String("/Helv 10 Tf 0 g")
    acroform.Fields.append(direct)
    page_one.obj.Annots.append(direct)

    string_choice = _widget(
        pdf,
        page_one,
        [72, 620, 252, 644],
        resources,
        field_type="/Ch",
        name="strings",
        options=pikepdf.Array([pikepdf.String(value) for value in STRING_OPTIONS]),
    )
    string_choice.I = pikepdf.Array([0])
    string_choice.V = pikepdf.String("")
    string_choice.DA = pikepdf.String("/Helv 10 Tf 0 g")
    acroform.Fields.append(string_choice)
    page_one.obj.Annots.append(string_choice)

    without_options = _widget(
        pdf, page_one, [72, 580, 252, 604], resources, field_type="/Ch", name="noopt"
    )
    without_options.V = pikepdf.String("")
    without_options.DA = pikepdf.String("/Helv 10 Tf 0 g")
    acroform.Fields.append(without_options)
    page_one.obj.Annots.append(without_options)

    note = _parent_field(pdf, "note", "/Tx", resources)
    acroform.Fields.append(note)
    note_widget = _widget(pdf, page_two, [72, 660, 252, 684], resources, parent=note)
    note.Kids.append(note_widget)
    page_two.obj.Annots.append(note_widget)
    pdf.save(path)
    pdf.close()


def _field(pdf: pikepdf.Pdf, name: str) -> pikepdf.Object:
    for field in pdf.Root.AcroForm.Fields:
        if str(field.get("/T", "")) == name:
            return field
    raise AssertionError(f"field {name!r} not found")


def _options(field: pikepdf.Object) -> list[tuple[str, str] | str]:
    if "/Opt" not in field:
        return []
    result: list[tuple[str, str] | str] = []
    for option in field.Opt:
        if isinstance(option, pikepdf.Array):
            result.append(tuple(str(value) for value in option))  # type: ignore[arg-type]
        else:
            result.append(str(option))
    return result


def _indices(field: pikepdf.Object) -> list[int] | None:
    if "/I" not in field:
        return None
    return [int(value) for value in field.I]


def _assert_field(
    pdf: pikepdf.Pdf,
    name: str,
    value: str,
    options: list[tuple[str, str] | str] | None = None,
    indices: list[int] | None = None,
) -> None:
    field = _field(pdf, name)
    assert str(field.get("/V", "")) == value, (name, field.get("/V"))
    if options is not None:
        assert _options(field) == options, (name, _options(field), options)
    actual_indices = _indices(field)
    if indices is None:
        assert actual_indices in (None, []), (name, actual_indices)
    else:
        assert actual_indices == indices, (name, actual_indices, indices)

    kids = list(field.get("/Kids", []))
    for widget in kids:
        effective = widget.get("/V", field.get("/V", ""))
        assert str(effective) == value, (name, "widget", effective, value)


def _assert_appearances(
    pdf: pikepdf.Pdf,
    choice_display: str | None = None,
    choice_export: str | None = None,
) -> None:
    for name in CHOICE_NAMES:
        field = _field(pdf, name)
        widgets = list(field.get("/Kids", [])) or [field]
        if name == "choice":
            assert len(widgets) == 2, len(widgets)
        for widget in widgets:
            appearance = widget.get("/AP")
            assert appearance is not None and "/N" in appearance, (name, "missing AP/N")
            normal = appearance.N
            assert hasattr(normal, "read_bytes") and normal.read_bytes(), (name, "empty AP/N")
            if name == "choice" and choice_display is not None:
                appearance_bytes = normal.read_bytes()
                display_token = f"({choice_display}) Tj".encode()
                assert display_token in appearance_bytes, (name, display_token, appearance_bytes)
                if choice_export is not None:
                    export_token = f"({choice_export}) Tj".encode()
                    assert export_token not in appearance_bytes, (name, export_token, appearance_bytes)


def fill(candidate, template: Path, values: list[tuple[str, str]], directory: Path, label: str) -> Path:
    result = Path(candidate.fill_template(str(template), data_strings=values, editable=True))
    assert result.is_file(), result
    output = directory / f"{label}.pdf"
    shutil.copyfile(result, output)
    result.unlink(missing_ok=True)
    return output


def assert_rendered(output: Path, directory: Path) -> None:
    pdftotext = shutil.which("pdftotext")
    pdftoppm = shutil.which("pdftoppm")
    assert pdftotext and pdftoppm, "Poppler pdftotext/pdftoppm is required"
    extracted = subprocess.run([pdftotext, str(output), "-"], check=True, capture_output=True).stdout.decode("utf-8", "replace")
    assert extracted.count("Bergen") == 2, extracted
    assert "Alice" in extracted, extracted
    prefix = directory / "rendered"
    subprocess.run([pdftoppm, "-f", "1", "-l", "2", "-png", str(output), str(prefix)], check=True, capture_output=True)
    rendered = sorted(directory.glob("rendered-*.png"))
    assert len(rendered) == 2 and all(item.stat().st_size > 1000 for item in rendered), rendered


def run_pass(candidate, directory: Path) -> None:
    template = directory / "fixture.pdf"
    build_fixture(template)
    pairs = list(PAIR_OPTIONS)

    blank = fill(candidate, template, [("choice", ""), ("direct", ""), ("strings", "A"), ("noopt", ""), ("note", "Blank")], directory, "blank")
    with pikepdf.Pdf.open(blank) as pdf:
        _assert_field(pdf, "choice", "", pairs + [""], [3])
        _assert_field(pdf, "direct", "", list(DIRECT_OPTIONS) + [""], [2])
        _assert_field(pdf, "strings", "A", STRING_OPTIONS, [0])
        _assert_field(pdf, "noopt", "", [""], None)
        _assert_field(pdf, "note", "Blank")
        _assert_appearances(pdf, choice_display="")

    matching = fill(candidate, template, [("choice", "02"), ("direct", "d2"), ("strings", "B"), ("noopt", "custom"), ("note", "Alice")], directory, "matching")
    with pikepdf.Pdf.open(matching) as pdf:
        _assert_field(pdf, "choice", "02", pairs, [1])
        _assert_field(pdf, "direct", "d2", list(DIRECT_OPTIONS), [1])
        _assert_field(pdf, "strings", "B", STRING_OPTIONS, [1])
        _assert_field(pdf, "noopt", "custom", ["custom"], None)
        _assert_field(pdf, "note", "Alice")
        _assert_appearances(pdf, choice_display="Bergen", choice_export="02")
        assert b"(Delta) Tj" in _field(pdf, "direct").AP.N.read_bytes()
    assert_rendered(matching, directory)

    zero = fill(candidate, template, [("choice", "00")], directory, "zero")
    with pikepdf.Pdf.open(zero) as pdf:
        _assert_field(pdf, "choice", "00", pairs, [0])
        _assert_appearances(pdf, choice_display=" ", choice_export="00")

    display = fill(candidate, template, [("choice", "Bergen")], directory, "display")
    with pikepdf.Pdf.open(display) as pdf:
        _assert_field(pdf, "choice", "Bergen", pairs + ["Bergen"], [3])

    strings = fill(candidate, template, [("strings", "B")], directory, "strings")
    with pikepdf.Pdf.open(strings) as pdf:
        _assert_field(pdf, "strings", "B", STRING_OPTIONS, [1])

    new_value = fill(candidate, template, [("noopt", "editable")], directory, "new-value")
    with pikepdf.Pdf.open(new_value) as pdf:
        _assert_field(pdf, "noopt", "editable", ["editable"], None)

    first = fill(candidate, template, [("choice", "02")], directory, "repeat-first")
    blank_again = fill(candidate, first, [("choice", "")], directory, "repeat-blank")
    final = fill(candidate, blank_again, [("choice", "02")], directory, "repeat-final")
    with pikepdf.Pdf.open(final) as pdf:
        _assert_field(pdf, "choice", "02", pairs + [""], [1])
        _assert_appearances(pdf, choice_display="Bergen", choice_export="02")

    with patch.object(candidate.pikepdf.Pdf, "generate_appearance_streams", side_effect=RuntimeError("probe")):
        restored = fill(candidate, template, [("choice", "02")], directory, "appearance-error")
    with pikepdf.Pdf.open(restored) as pdf:
        _assert_field(pdf, "choice", "02", pairs, [1])


def run_expected_failure(candidate, directory: Path) -> None:
    template = directory / "fixture.pdf"
    build_fixture(template)
    output = fill(candidate, template, [("choice", "02")], directory, "control")
    with pikepdf.Pdf.open(output) as pdf:
        options = _field(pdf, "choice").Opt
        corrupted = (
            len(options) > len(PAIR_OPTIONS)
            and any(not isinstance(item, pikepdf.Array) for item in options)
            and any(str(item).startswith("pikepdf.Array(") for item in options)
            and any(str(item) == "02" for item in options)
        )
    if not corrupted:
        raise AssertionError("control FAILED: stock option-pair corruption was not reproduced")
    print("control ok: stock fill_template flattened /Opt pairs and appended scalar export")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("expect-fail", "expect-pass"))
    parser.add_argument("--module", help="candidate pdftk.py to load; default is installed docassemble.base.pdftk")
    args = parser.parse_args()
    try:
        candidate = load_candidate(args.module)
        with tempfile.TemporaryDirectory(prefix="pdf-choice-check-") as raw_directory:
            directory = Path(raw_directory)
            if args.mode == "expect-fail":
                run_expected_failure(candidate, directory)
            else:
                run_pass(candidate, directory)
    except Exception as err:  # noqa: BLE001 - a harness failure needs context
        print(f"FAIL {args.mode}: {type(err).__name__}: {err}")
        return 1
    print(f"PASS {args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
