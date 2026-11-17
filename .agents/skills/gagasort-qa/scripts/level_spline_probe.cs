// 仅映射几何相关 DTO 并调用生产方法；不替代正式反序列化、完整 Validator、Editor 或设备验收。
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using GagaSort;
class GeometryProbe {
 static GagaSortGridPosition Position(JsonElement j)=>new(j[0].GetSingle(),j[1].GetSingle());
 static GagaSortLevelData Parse(JsonElement j) {
  var l=new GagaSortLevelData{LevelId=j.GetProperty("number").GetInt32(),LevelMode=LevelMode.Main,BoardSize=j.GetProperty("board_size").GetInt32(),FormatVersion=j.GetProperty("format_version").GetInt32()};
  var b=l.Belt;b.LoopMode=(EGagaSortBeltLoopMode)j.GetProperty("loop_mode").GetInt32();
  foreach(var n in j.GetProperty("nodes").EnumerateArray())b.PathNodes.Add(Position(n));
  foreach(var c in j.GetProperty("curves").EnumerateArray()) {
   if(c.ValueKind==JsonValueKind.Null){b.PathNodeCurves.Add(null);continue;}
   b.PathNodeCurves.Add(new GagaSortPathNodeCurveData{TangentMode=(EGagaSortPathTangentMode)c[0].GetInt32(),InControlPoint=Position(c[1]),OutControlPoint=Position(c[2]),InControlElevation=c.GetArrayLength()>3?c[3].GetSingle():0,OutControlElevation=c.GetArrayLength()>4?c[4].GetSingle():0,Has3DControlPoints=c.GetArrayLength()>5&&c[5].GetBoolean()});
  }
  foreach(var v in j.GetProperty("elevations").EnumerateArray())b.PathNodeElevations.Add(v.GetSingle());
  foreach(var c in j.GetProperty("elevation_curves").EnumerateArray()) {
   if(c.ValueKind==JsonValueKind.Null){b.PathNodeElevationCurves.Add(null);continue;}
   b.PathNodeElevationCurves.Add(new GagaSortPathNodeElevationCurveData{Mode=(EGagaSortElevationCurveMode)c[0].GetInt32(),InControlElevation=c[1].GetSingle(),OutControlElevation=c[2].GetSingle()});
  }
  foreach(var s in j.GetProperty("slots").EnumerateArray()) {
   var x=new GagaSortSlotLevelData{SlotId=s.GetProperty("id").GetInt32(),AnchorPosition=Position(s.GetProperty("anchor")),CheckPointPosition=Position(s.GetProperty("cp")),WidthCells=s.GetProperty("width").GetInt32(),LengthCells=s.GetProperty("length").GetInt32(),ExitDirection=(EGagaSortDirection)s.GetProperty("direction").GetInt32(),SlotType=(EGagaSortSlotType)s.GetProperty("slot_type").GetInt32(),BlockingEmitterSlotId=s.GetProperty("rear").GetInt32()};
   var c=s.GetProperty("cover");x.Cover.CoverType=(EGagaSortSlotCoverType)c[0].GetInt32();x.Cover.TargetColor=(EGagaSortDuckColor)c[1].GetInt32();
   foreach(var v in c[3].EnumerateArray())x.Cover.ActivationSourceSlotIds.Add(v.GetInt32());
   foreach(var v in c[4].EnumerateArray())x.Cover.ActivationSourceSides.Add((EGagaSortDirection)v.GetInt32());
   l.Slots.Add(x);
  }
  return l;
 }
 static object[] Slots(GagaSortLevelData l)=>l.Slots.Select(s=>(object)new{id=s.SlotId,anchor=new[]{s.AnchorPosition.X,s.AnchorPosition.Y},cp=new[]{s.CheckPointPosition.X,s.CheckPointPosition.Y},width=s.WidthCells,length=s.LengthCells,direction=(int)s.ExitDirection,rear=s.BlockingEmitterSlotId}).ToArray();
 static object Geometry(GagaSortLevelData level,IReadOnlyList<GagaSortGridPosition> path) {
  var bounds=level.Slots.ToDictionary(s=>s.SlotId,s=>GagaSortGridGeometryUtility.CreateContinuousRect(s.AnchorPosition,s.WidthCells,s.LengthCells,s.ExitDirection));
  var slots=new List<object>();var overlaps=new List<int[]>();
  foreach(var slot in level.Slots) {
   var rect=bounds[slot.SlotId];var covered=new List<int>();
   for(int i=0;i<path.Count;i++)if(rect.Contains(path[i]))covered.Add(i);
   bool found=GagaSortPathBuilder.TryGetNearestProgress(path,level.Belt.LoopMode,slot.CheckPointPosition,out float progress,out float distance);
   slots.Add(new{id=slot.SlotId,bounds=new[]{rect.MinX,rect.MaxX,rect.MinY,rect.MaxY},covered_path_indices=covered,nearest_progress_found=found,nearest_progress=progress,check_point_distance=distance,anchor_derived=slot.BlockingEmitterSlotId!=0?(bool?)null:GagaSortPoolGeometry.IsAnchorDerivedFromCheckPoint(slot.AnchorPosition,slot.CheckPointPosition,slot.ExitDirection,slot.LengthCells)});
   foreach(var other in level.Slots)if(other.SlotId>slot.SlotId&&rect.Overlaps(bounds[other.SlotId]))overlaps.Add(new[]{slot.SlotId,other.SlotId});
  }
  return new{slots,pool_overlap_pairs=overlaps};
 }
 static void Main(string[] args) {
  if(args.Length==0){
   var p=new List<GagaSortGridPosition>();
   bool ok=GagaSortPathBuilder.TryExpand(new[]{new GagaSortGridPosition(0,0),new GagaSortGridPosition(10,0)},EGagaSortBeltLoopMode.PortalLoop,2.5f,p,out var e);
   if(!ok||p.Count<2||Math.Abs(p[0].X)>0.0001||Math.Abs(p[^1].X-10)>0.0001)throw new Exception(e+" line mismatch");
   Console.WriteLine("PASS production straight path; samples="+p.Count);
   ok=GagaSortPathBuilder.TryExpand(new[]{new GagaSortGridPosition(0,0),new GagaSortGridPosition(10,0),new GagaSortGridPosition(10,10)},EGagaSortBeltLoopMode.PortalLoop,2.5f,p,out e);
   if(!ok||!p.Any(v=>v.X>7.5&&v.X<10&&v.Y>0&&v.Y<2.5))throw new Exception(e+" no rounded arc");
   Console.WriteLine("PASS production quarter-circle path; samples="+p.Count);return;
  }
  using var doc=JsonDocument.Parse(File.ReadAllText(args[0]));var results=new List<object>();int pass=0,fail=0;
  float radius=args.Length>2?float.Parse(args[2],System.Globalization.CultureInfo.InvariantCulture):2.5f;
  foreach(var input in doc.RootElement.GetProperty("levels").EnumerateArray()) {
   string id=input.GetProperty("level_id").GetString();
   try {
    var l=Parse(input);var b=l.Belt;var p=new List<GagaSortGridPosition>();var heights=new List<float>();
    bool ok=GagaSortPathBuilder.TryExpand(b.PathNodes,b.PathNodeCurves,b.PathNodeElevationCurves,b.PathNodeElevations,b.LoopMode,radius,p,heights,out var err);
    bool resolved=ok&&GagaSortPoolRelationGeometry.TryResolve(l,p,b.LoopMode,out err);
    results.Add(new{level_id=id,expand_ok=ok,resolve_ok=resolved,error=err,expanded_path=p.Select(v=>new[]{v.X,v.Y}).ToArray(),expanded_elevations=heights.ToArray(),resolved_slots=Slots(l),geometry_checks=resolved?Geometry(l,p):null});
    if(resolved)pass++;else fail++;
   }catch(Exception ex){fail++;results.Add(new{level_id=id,expand_ok=false,resolve_ok=false,error=ex.ToString()});}
  }
  File.WriteAllText(args[1],JsonSerializer.Serialize(new{radius,passed=pass,failed=fail,levels=results}));Console.WriteLine("levels="+results.Count+" expand+resolve passed="+pass+" failed="+fail);
 }
}
