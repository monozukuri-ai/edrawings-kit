"""Definition ownership remains available without qualified world placements."""

import json
import struct

import edrawings_kit as ed
import pytest
from edrawings_kit import _core
from test_scene import shell
from test_style_resolution import opened
from test_views import compressed, raw


@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
@pytest.mark.parametrize("withhold_placements", [False, True])
def test_nested_reopened_definitions_keep_owner_across_references(
    wrapper, withhold_placements, zip_factory
):
    line = b"l" + struct.pack("<6f", 0, 0, 0, 100, 0, 0)
    # Root line, nested definition, tag the segment, then use it elsewhere.
    body = line + opened(b"sheet-a") + opened(b"geometry") + line + shell()
    body += b")q)" + opened(b"sheet-b") + b"<\x11/sheet-a/geometry)"
    # Reopen by tag: newly inserted definitions have the original node owner.
    body += b"s\0\0\0\0" + line + b")"
    if withhold_placements:
        # A supported text payload with unevaluated layout region prevents
        # global placement qualification, but not definition ownership.
        body += b"x" + bytes(12) + b"\x05\x02A\0\x01\0\x02" + bytes(24)
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    drawing = ed.read(data).read_drawing()
    s = drawing.summary.scene
    assert drawing.summary.to_dict() == json.loads(
        _core.read_bytes(data, "{}").read_drawing().summary_json()
    )
    assert [n.name for n in s.nodes] == ["/", "sheet-a", "geometry", "sheet-b"]
    expected = [s.nodes[0].id, s.nodes[2].id, s.nodes[2].id]
    if withhold_placements:
        expected.append(s.nodes[0].id)
    assert [p.owner_node_id for p in s.primitives] == expected
    assert s.meshes[0].owner_node_id == s.nodes[2].id
    assert s.nodes[2].parent_id == s.nodes[1].id
    assert all(p.owner_node_id != s.nodes[3].id for p in s.primitives)
    assert drawing.summary.assessment.sheet_status == "unsupported"
    if withhold_placements:
        assert s.placement_status == "unsupported"
        assert not s.instances and not s.primitive_instances
    else:
        assert s.placement_status == "complete"
        assert len(s.instances) == 2 and len(s.primitive_instances) == 5
    assert drawing.source_bytes(s.primitives[1].source) == line
