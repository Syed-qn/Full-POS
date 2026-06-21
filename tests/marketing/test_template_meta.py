"""MetaTemplateProvider component-builder unit tests (pure functions, no network).

The provider itself can't be instantiated under marketing_send_dry_run, but
_build_components / _body_example_values are module-level pure functions, so we
test the payload shaping directly.
"""
from app.marketing.template_meta import _body_example_values, _build_components
from app.marketing.template_port import TemplateSpec


def _spec(body: str, header: dict | None = None) -> TemplateSpec:
    return TemplateSpec(
        name="x", language="en", category="marketing",
        body=body, header=header, footer=None, buttons=[],
    )


def test_body_with_variable_gets_example():
    """Meta hard-400s (subcode 2388043) an IMAGE-header template whose BODY has a
    {{1}} but no example — so the BODY component must carry example.body_text."""
    comps = _build_components(_spec("Hi {{1}}, 20% off! Reply to order."))
    body = next(c for c in comps if c["type"] == "BODY")
    assert body["example"] == {"body_text": [["Ahmed"]]}


def test_body_without_variables_has_no_example():
    comps = _build_components(_spec("Flat 20% off all biryani today. Reply to order."))
    body = next(c for c in comps if c["type"] == "BODY")
    assert "example" not in body


def test_multiple_variables_get_one_sample_each_in_order():
    vals = _body_example_values("Hi {{1}}, your code {{2}} unlocks {{3}}.")
    assert vals == ["Ahmed", "Sample", "Sample"]


def test_image_header_and_body_variable_both_carry_examples():
    """The real failing case: IMAGE header + {{1}} body. Header gets its handle
    example, BODY gets its body_text example — neither component is missing one."""
    comps = _build_components(
        _spec("Hi {{1}}, treat yourself! Reply to order.",
              header={"type": "IMAGE", "image_url": "https://x/y.jpg"}),
        header_handle="h:abc",
    )
    header = next(c for c in comps if c["type"] == "HEADER")
    body = next(c for c in comps if c["type"] == "BODY")
    assert header["example"] == {"header_handle": ["h:abc"]}
    assert body["example"] == {"body_text": [["Ahmed"]]}
