using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using GagaSort;

// JSON adapter only. Geometry algorithms are compiled from the repository's production files.
internal static class LevelGeometryProbe {
    private static float[] Point(GagaSortGridPosition value) => new[] { value.X, value.Y };

    private static GagaSortGridPosition ReadPoint(JsonElement value) {
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 2) {
            throw new FormatException("position must be [x,y]");
        }
        var x = value[0].GetSingle();
        var y = value[1].GetSingle();
        if (!float.IsFinite(x) || !float.IsFinite(y)) throw new FormatException("position must be finite");
        return new GagaSortGridPosition(x, y);
    }

    private static object Rect(GagaSortContinuousRect rect) => new {
        min_x = rect.MinX, max_x = rect.MaxX, min_y = rect.MinY, max_y = rect.MaxY,
    };

    // A one-cell production rect represents a point, preserving the production boundary tolerance.
    private static bool Inside(GagaSortGridPosition point, int size) =>
        GagaSortGridGeometryUtility.CreateContinuousRect(point, 1, 1, EGagaSortDirection.Up).IsInsideBoard(size);

    private static object CheckLevel(JsonElement input) {
        var id = input.GetProperty("level_id").Clone();
        var size = input.GetProperty("board_size").GetInt32();
        var issues = new List<object>();
        var skipGeometry = input.TryGetProperty("skip_geometry", out var skip) && skip.GetBoolean();
        var nodes = new List<(int Index, GagaSortGridPosition Point)>();
        var nodeResults = new List<object>();
        foreach (var value in input.GetProperty("nodes").EnumerateArray()) {
            try {
                var point = ReadPoint(value);
                nodes.Add((nodeResults.Count, point));
                nodeResults.Add(new { index = nodeResults.Count, position = Point(point),
                    inside_board = size > 0 && Inside(point, size), half_grid_aligned = point.IsHalfGridAligned() });
            } catch (Exception error) {
                issues.Add(new { field = "nodes[" + nodeResults.Count + "]", error = error.Message });
                nodeResults.Add(new { index = nodeResults.Count, invalid = true });
            }
        }

        var slots = new List<object>();
        var inputRects = new List<(int Id, GagaSortContinuousRect Rect)>();
        var derivedRects = new List<(int Id, GagaSortContinuousRect Rect)>();
        var dtoById = new Dictionary<int, GagaSortSlotLevelData>();
        var rawById = new Dictionary<int, JsonElement>();
        foreach (var value in input.GetProperty("slots").EnumerateArray()) {
            try {
                var slotId = value.GetProperty("id").GetInt32();
                var rear = value.TryGetProperty("rear", out var rearValue) ? rearValue : default;
                if (rear.ValueKind != JsonValueKind.Undefined && rear.ValueKind != JsonValueKind.True
                    && rear.ValueKind != JsonValueKind.False && rear.ValueKind != JsonValueKind.Number) {
                    throw new FormatException("rear must be boolean or integer front slot id");
                }
                var blockingId = rear.ValueKind == JsonValueKind.Number ? rear.GetInt32() : 0;
                if (blockingId < 0) throw new FormatException("rear id cannot be negative");
                var slot = new GagaSortSlotLevelData {
                    SlotId = slotId, AnchorPosition = ReadPoint(value.GetProperty("anchor")),
                    CheckPointPosition = ReadPoint(value.GetProperty("cp")),
                    WidthCells = value.GetProperty("width").GetInt32(),
                    LengthCells = value.GetProperty("length").GetInt32(),
                    ExitDirection = (EGagaSortDirection)value.GetProperty("direction").GetByte(),
                    BlockingEmitterSlotId = blockingId,
                };
                if (!dtoById.TryAdd(slotId, slot)) throw new FormatException("duplicate slot id: " + slotId);
                rawById.Add(slotId, value);
            } catch (Exception error) {
                issues.Add(new { field = "slot_input", input = value.Clone(), error = error.Message });
            }
        }

        foreach (var pair in dtoById) {
            var slot = pair.Value;
            try {
                if (skipGeometry) {
                    slots.Add(new { id = slot.SlotId, cp = Point(slot.CheckPointPosition),
                        cp_inside_board = size > 0 && Inside(slot.CheckPointPosition, size), geometry_skipped = true });
                    continue;
                }
                var raw = rawById[pair.Key];
                var unknownRear = raw.TryGetProperty("rear", out var rear) && rear.ValueKind == JsonValueKind.True;
                var rect = GagaSortGridGeometryUtility.CreateContinuousRect(slot.AnchorPosition,
                    slot.WidthCells, slot.LengthCells, slot.ExitDirection);
                inputRects.Add((slot.SlotId, rect));
                GagaSortGridPosition? expected = null;
                string derivation;
                if (slot.BlockingEmitterSlotId > 0) {
                    if (dtoById.TryGetValue(slot.BlockingEmitterSlotId, out var front) && front != slot) {
                        expected = GagaSortPoolGeometry.CalculateBlockingRearAnchor(front, slot);
                        derivation = "production_rear_from_input_front_anchor";
                    } else {
                        derivation = "missing_or_self_front";
                    }
                } else if (unknownRear) {
                    derivation = "rear_front_identity_not_supplied";
                } else {
                    expected = GagaSortPoolGeometry.CalculateAnchor(slot.CheckPointPosition, slot.ExitDirection, slot.LengthCells);
                    derivation = "production_checkpoint_anchor";
                }
                object derivedRect = null;
                if (expected.HasValue) {
                    var bounds = GagaSortGridGeometryUtility.CreateContinuousRect(expected.Value,
                        slot.WidthCells, slot.LengthCells, slot.ExitDirection);
                    derivedRect = Rect(bounds);
                    derivedRects.Add((slot.SlotId, bounds));
                }
                var matching = expected.HasValue ?
                    (bool?)(slot.BlockingEmitterSlotId == 0
                        ? GagaSortPoolGeometry.IsAnchorDerivedFromCheckPoint(slot.AnchorPosition,
                            slot.CheckPointPosition, slot.ExitDirection, slot.LengthCells)
                        : Math.Abs(slot.AnchorPosition.X - expected.Value.X) <= .0001f
                            && Math.Abs(slot.AnchorPosition.Y - expected.Value.Y) <= .0001f) : null;
                slots.Add(new {
                    id = slot.SlotId, anchor = Point(slot.AnchorPosition), cp = Point(slot.CheckPointPosition),
                    direction = (int)slot.ExitDirection, rect = Rect(rect),
                    anchor_inside_board = size > 0 && Inside(slot.AnchorPosition, size),
                    cp_inside_board = size > 0 && Inside(slot.CheckPointPosition, size),
                    pool_inside_board = size > 0 && rect.IsInsideBoard(size),
                    pool_outside_board_is_not_runtime_error = true,
                    input_nodes_inside_pool = nodes.Where(item => rect.Contains(item.Point)).Select(item => item.Index).ToArray(),
                    anchor_derivation = derivation,
                    derived_anchor = expected.HasValue ? Point(expected.Value) : null,
                    derived_rect = derivedRect, input_anchor_matches_derived = matching,
                });
            } catch (Exception error) {
                issues.Add(new { field = "slots[" + slot.SlotId + "]", error = error.Message });
            }
        }
        List<object> Pairs(List<(int Id, GagaSortContinuousRect Rect)> rects) {
            var result = new List<object>();
            for (var i = 0; i < rects.Count; i++) {
                for (var j = i + 1; j < rects.Count; j++) {
                    if (rects[i].Rect.Overlaps(rects[j].Rect)) {
                        result.Add(new { first = rects[i].Id, second = rects[j].Id });
                    }
                }
            }
            return result;
        }
        return new { level_id = id, board_size = size, board_size_valid = size > 0, slots_geometry_skipped = skipGeometry,
            nodes = nodeResults, slots, input_overlaps = Pairs(inputRects),
            derived_overlaps = Pairs(derivedRects), issues };
    }

    private static object SelfTest() {
        var checks = new List<string>();
        void Assert(bool value, string name) {
            if (!value) throw new Exception("self-test failed: " + name);
            checks.Add(name);
        }
        var first = GagaSortGridGeometryUtility.CreateContinuousRect(new GagaSortGridPosition(2, 2), 2, 4, EGagaSortDirection.Up);
        var edge = GagaSortGridGeometryUtility.CreateContinuousRect(new GagaSortGridPosition(3, 2), 2, 4, EGagaSortDirection.Up);
        var corner = GagaSortGridGeometryUtility.CreateContinuousRect(new GagaSortGridPosition(3, 5), 2, 4, EGagaSortDirection.Up);
        var clear = GagaSortGridGeometryUtility.CreateContinuousRect(new GagaSortGridPosition(3.001f, 2), 2, 4, EGagaSortDirection.Up);
        Assert(first.Overlaps(edge), "shared_edge_is_overlap");
        Assert(first.Overlaps(corner), "shared_corner_is_overlap");
        Assert(!first.Overlaps(clear), "gap_above_tolerance_is_separate");
        Assert(first.Contains(new GagaSortGridPosition(1.5f, .5f)), "rect_boundary_is_contained");
        Assert(Inside(new GagaSortGridPosition(0, 9), 10), "board_boundary_is_inside");
        Assert(!Inside(new GagaSortGridPosition(-.001f, 9), 10), "outside_above_tolerance_is_outside");
        var rotated = GagaSortGridGeometryUtility.CreateContinuousRect(new GagaSortGridPosition(2, 2), 2, 4, EGagaSortDirection.Right);
        Assert(rotated.MinX == .5f && rotated.MaxY == 2.5f, "right_direction_swaps_dimensions");
        Assert(GagaSortPoolGeometry.CalculateAnchor(new GagaSortGridPosition(10, 10), EGagaSortDirection.Up, 4)
            .Equals(new GagaSortGridPosition(10, 4)), "production_cp_anchor_offset");
        var front = new GagaSortSlotLevelData { AnchorPosition = new GagaSortGridPosition(10, 4), LengthCells = 4, ExitDirection = EGagaSortDirection.Up };
        Assert(GagaSortPoolGeometry.CalculateBlockingRearAnchor(front, new GagaSortSlotLevelData { LengthCells = 2 })
            .Equals(new GagaSortGridPosition(10, 0)), "production_rear_anchor_offset");
        return new { passed = true, checks };
    }

    public static int Main(string[] args) {
        try {
            object result;
            if (args.Length == 1 && args[0] == "--self-test") result = SelfTest();
            else {
                if (args.Length != 1) throw new ArgumentException("usage: LevelGeometryProbe <input.json|-> or --self-test");
                using var document = JsonDocument.Parse(args[0] == "-" ? Console.In.ReadToEnd() : File.ReadAllText(args[0]));
                var root = document.RootElement;
                var levels = root.TryGetProperty("levels", out var array) ? array.EnumerateArray().ToArray() : new[] { root };
                var records = new List<object>();
                foreach (var level in levels) {
                    try { records.Add(CheckLevel(level)); }
                    catch (Exception error) { records.Add(new { invalid_level = level.Clone(), error = error.Message }); }
                }
                result = new { tool = "gagasort-production-geometry-kernel", scope = "rectangles_and_cp_anchor_only",
                    full_validator_executed = false, curves_checked = false, solver_executed = false,
                    node_collisions_are_control_nodes_only = true, levels = records };
            }
            Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        } catch (Exception error) {
            Console.Error.WriteLine(error.ToString());
            return 2;
        }
    }
}
