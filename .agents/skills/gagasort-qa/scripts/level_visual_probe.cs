// 生产代码仅隔离Mesh原生容器与未运行场景装配；检测器不替代生产生成算法。
using System;
using System.Collections.Generic;
using System.Linq;
using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Security.Cryptography;
using UnityEngine;
using UnityEngine.Rendering;
using GagaSort;
namespace GagaSort {
 public class GagaSortBeltData { public EGagaSortBeltLoopMode LoopMode {get;set;} }
 internal sealed class WaterPipeSharedMeshData {
  public ProbeMesh ShadowMesh,ChannelShellMesh,WaterSurfaceMesh;
  public WaterPipeSharedMeshData(ProbeMesh a,ProbeMesh b,ProbeMesh c){ShadowMesh=a;ChannelShellMesh=b;WaterSurfaceMesh=c;}
 }
 internal sealed class ProbeMesh {
  public string name;public HideFlags hideFlags;public IndexFormat indexFormat;
  public Vector3[] vertices;public int[] triangles;
  public void SetVertices(List<Vector3> v){vertices=v.ToArray();}
  public void SetUVs<T>(int n,List<T> v){}
  public void SetColors(List<Color> v){}
  public void SetTriangles(List<int> t,int n){triangles=t.ToArray();}
  public void RecalculateBounds(){}public void RecalculateNormals(){}
 }
}
class VisualProbe {
 const double AreaTolerance=0.00001;
 static double Cross(Vector3 a,Vector3 b,Vector3 c)=>(double)(b.x-a.x)*(c.y-a.y)-(double)(b.y-a.y)*(c.x-a.x);
 static float[][] Verts(IEnumerable<Vector3> vs)=>vs.Select(v=>new[]{v.x,v.y,v.z}).ToArray();
 static float[][] Points(IEnumerable<Vector3> vs)=>vs.Select(v=>new[]{v.x,v.y}).ToArray();
 static string MeshHash(ProbeMesh m)=>Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(new{v=Verts(m.vertices),t=m.triangles})));
 static double PolygonArea(List<Vector3> p){double a=0;for(int i=0;i<p.Count;i++)a+=(double)p[i].x*p[(i+1)%p.Count].y-(double)p[(i+1)%p.Count].x*p[i].y;return Math.Abs(a)*.5;}
 // Sutherland-Hodgman 三角形裁剪；正面积才算风险，边界接触不算。
 static double IntersectionArea(Vector3[] a,Vector3[] b){
  var p=a.ToList();double sign=Math.Sign(Cross(b[0],b[1],b[2]));if(sign==0)return 0;
  for(int e=0;e<3&&p.Count>0;e++){
   var q=new List<Vector3>();var u=b[e];var v=b[(e+1)%3];
   for(int i=0;i<p.Count;i++){
    var x=p[i];var y=p[(i+1)%p.Count];double dx=Cross(u,v,x)*sign,dy=Cross(u,v,y)*sign;bool ix=dx>=0,iy=dy>=0;
    if(ix)q.Add(x);
    if(ix!=iy){double t=dx/(dx-dy);q.Add(x+(y-x)*(float)t);}
   }p=q;
  }return p.Count>=3?PolygonArea(p):0;
 }
 static object Analyze(string kind,List<Vector3> path,bool closed,WaterPipeBuildSettings settings,string source,object recipeValidation=null){
  var mesh=new WaterPipeMeshBuilder(null,settings).BuildSharedMeshData(path,closed);var water=mesh.WaterSurfaceMesh;var shell=mesh.ChannelShellMesh;
  int folds=0;var foldEvidence=new List<object>();
  // 按生成三角形索引过滤水面中央实体条带，羽化条带单列不影响主判定。
  for(int k=0;k<water.triangles.Length;k+=3){var ids=new[]{water.triangles[k],water.triangles[k+1],water.triangles[k+2]};if(ids.Any(x=>x%4==0||x%4==3))continue;var v=ids.Select(x=>water.vertices[x]).ToArray();double area=Cross(v[0],v[1],v[2]);if(area < -AreaTolerance){folds++;if(foldEvidence.Count<20)foldEvidence.Add(new{triangle=k/3,indices=ids,vertices=Verts(v),points=Points(v),signed_area=area});}}
  var walls=new List<(int id,int row,int side,Vector3[] v,float minX,float maxX,float minY,float maxY)>();
  for(int k=0;k<shell.triangles.Length;k+=3){var ids=new[]{shell.triangles[k],shell.triangles[k+1],shell.triangles[k+2]};int side=ids.All(x=>x%8==1||x%8==2)?1:ids.All(x=>x%8==5||x%8==6)?-1:0;if(side==0)continue;var v=ids.Select(x=>shell.vertices[x]).ToArray();if(Math.Abs(Cross(v[0],v[1],v[2]))<=AreaTolerance)continue;walls.Add((k/3,ids.Min()/8,side,v,v.Min(x=>x.x),v.Max(x=>x.x),v.Min(x=>x.y),v.Max(x=>x.y)));}
  int overlap=0,remoteOverlap=0;double maxOverlapArea=0;var overlapEvidence=new List<(double priority,object value)>();bool flat=path.All(v=>Math.Abs(v.z-path[0].z)<.00001f);int rows=shell.vertices.Length/8;
  var centers=Enumerable.Range(0,rows).Select(r=>(shell.vertices[r*8+3]+shell.vertices[r*8+4])*.5f).ToList();var arc=new double[rows];for(int r=1;r<rows;r++)arc[r]=arc[r-1]+Vector3.Distance(centers[r-1],centers[r]);
  double remoteThreshold=(settings.WaterChannelWidth+2*settings.WallWidth)*2;
  if(flat){
   var sorted=walls.OrderBy(x=>x.minX).ToArray();
   for(int i=0;i<sorted.Length;i++)for(int j=i+1;j<sorted.Length&&sorted[j].minX<sorted[i].maxX;j++){
    var x=sorted[i];var y=sorted[j];int distance=Math.Abs(x.row-y.row);if(x.side==y.side&&(distance<=1||closed&&distance>=rows-2))continue;
    if(x.maxY<=y.minY||y.maxY<=x.minY)continue;double area=IntersectionArea(x.v,y.v);if(area<=AreaTolerance)continue;
    double separation=Math.Abs(arc[x.row]-arc[y.row]);if(closed)separation=Math.Min(separation,arc[^1]-separation);bool remote=separation>remoteThreshold;
    overlap++;if(remote)remoteOverlap++;maxOverlapArea=Math.Max(maxOverlapArea,area);
    overlapEvidence.Add((area+(remote?1000:0),new{triangles=new[]{x.id,y.id},rows=new[]{x.row,y.row},sides=new[]{x.side,y.side},vertices=new[]{Verts(x.v),Verts(y.v)},points=Points(x.v.Concat(y.v)),intersection_area=area,path_separation=separation,nonlocal=remote}));
    if(overlapEvidence.Count>40)overlapEvidence=overlapEvidence.OrderByDescending(e=>e.priority).Take(20).ToList();
   }
  }
  // 风险图使用生产索引对应的真实三角形，不能用中心线描边近似水面或岸壁宽度。
  bool plot=folds>0||remoteOverlap>0;
  var plotWater=plot?Enumerable.Range(0,water.triangles.Length/3).Select(t=>Points(Enumerable.Range(t*3,3).Select(i=>water.vertices[water.triangles[i]]))).ToArray():null;
  var plotWalls=plot?walls.Select(w=>Points(w.v)).ToArray():null;
  return new{kind,source,units="grid_cells; XY matches geometry-input; local Z=-elevation",recipe_validation=recipeValidation,input_count=path.Count,sample_rows=rows,samples=Verts(centers),flat,limitations=flat?Array.Empty<string>():new[]{"wall_overlap not checked for nonflat path; XY projection cannot establish 3D wall intersections","water_fold checks XY projection only for nonflat path; not a 3D winding assertion"},mesh_hashes=new{water=MeshHash(water),shell=MeshHash(shell)},plot_water_triangles=plotWater,plot_wall_triangles=plotWalls,water_fold=new{count=folds,evidence=foldEvidence,status=flat?"checked_xy_flat":"checked_xy_projection_nonflat"},wall_overlap=new{count=overlap,nonlocal_count=remoteOverlap,local_count=overlap-remoteOverlap,nonlocal_path_distance_threshold=remoteThreshold,max_intersection_area=maxOverlapArea,evidence=overlapEvidence.OrderByDescending(e=>e.priority).Take(20).Select(e=>e.value),status=flat?"checked_xy_flat":"not_checked_nonflat"}};
 }
 static List<Vector3> DecodeRecipe(JsonElement entry){
  var t=typeof(WaterPipeRecipeLibrary).GetNestedType("Entry",BindingFlags.NonPublic|BindingFlags.Public);var e=System.Runtime.Serialization.FormatterServices.GetUninitializedObject(t);
  foreach(var pair in new[]{("Mode",(object)(LevelMode)entry.GetProperty("mode").GetInt32()),("LevelId",(object)entry.GetProperty("number").GetInt32()),("SampleCount",(object)entry.GetProperty("count").GetInt32()),("Data",(object)Convert.FromHexString(entry.GetProperty("hex").GetString()))})t.GetField(pair.Item1,BindingFlags.NonPublic|BindingFlags.Public|BindingFlags.Instance).SetValue(e,pair.Item2);
  return (List<Vector3>)typeof(WaterPipeRecipeLibrary).GetMethod("DecodeSamples",BindingFlags.NonPublic|BindingFlags.Static).Invoke(null,new[]{e});
 }
 static void Smoke(WaterPipeBuildSettings settings){
  var a=new[]{new Vector3(0,0),new Vector3(3,0),new Vector3(0,3)};var b=new[]{new Vector3(.5f,.5f),new Vector3(2,.5f),new Vector3(.5f,2)};
  if(IntersectionArea(a,b)<1||IntersectionArea(a,new[]{new Vector3(5,5),new Vector3(6,5),new Vector3(5,6)})>AreaTolerance||IntersectionArea(a,new[]{new Vector3(3,0),new Vector3(4,0),new Vector3(3,1)})>AreaTolerance)throw new Exception("intersection detector failed");
  var straight=Analyze("smoke",new List<Vector3>{new(0,0),new(10,0)},false,settings,"synthetic");
  var j=JsonSerializer.SerializeToElement(straight);if(j.GetProperty("water_fold").GetProperty("count").GetInt32()!=0||j.GetProperty("wall_overlap").GetProperty("count").GetInt32()!=0)throw new Exception("straight false positive");
  var tight=Enumerable.Range(0,21).Select(i=>new Vector3(.5f*(float)Math.Cos(i*Math.PI/20),.5f*(float)Math.Sin(i*Math.PI/20))).ToList();
  var t=JsonSerializer.SerializeToElement(Analyze("smoke",tight,false,settings,"synthetic tight bend"));if(t.GetProperty("water_fold").GetProperty("count").GetInt32()==0)throw new Exception("tight bend fold false negative");
  var crossing=new List<Vector3>{new(-5,-5),new(5,5),new(-5,5),new(5,-5)};
  var c=JsonSerializer.SerializeToElement(Analyze("smoke",crossing,false,settings,"synthetic crossing"));if(c.GetProperty("wall_overlap").GetProperty("nonlocal_count").GetInt32()==0)throw new Exception("crossing wall false negative");
  Console.WriteLine("PASS detector overlap/disjoint/touching and production straight/tight-bend/crossing meshes");
 }
 static void Main(string[] args){
  using var inputs=JsonDocument.Parse(File.ReadAllText(args[0]));using var config=JsonDocument.Parse(File.ReadAllText(args[1]));float radius=float.Parse(args[3],System.Globalization.CultureInfo.InvariantCulture);var settings=new WaterPipeBuildSettings();
  foreach(var prop in config.RootElement.GetProperty("settings").EnumerateObject()){var f=typeof(WaterPipeBuildSettings).GetField(prop.Name);f.SetValue(settings,f.FieldType==typeof(Vector2)?(object)new Vector2(prop.Value[0].GetSingle(),prop.Value[1].GetSingle()):f.FieldType==typeof(int)?(object)prop.Value.GetInt32():prop.Value.GetSingle());}
  Smoke(settings);var recipes=new Dictionary<int,List<(JsonElement library,JsonElement entry)>>();
  foreach(var lib in config.RootElement.GetProperty("recipes").EnumerateArray())foreach(var e in lib.GetProperty("entries").EnumerateArray()){int n=e.GetProperty("number").GetInt32();if(!recipes.ContainsKey(n))recipes[n]=new();recipes[n].Add((lib,e));}
  var levels=new List<object>();int errors=0;
  foreach(var input in inputs.RootElement.GetProperty("levels").EnumerateArray()){
   var sources=new List<object>();int number=input.GetProperty("number").GetInt32();string id=input.GetProperty("level_id").GetString();
   try{
    var l=GeometryInput.Parse(input);var b=l.Belt;var board=new GagaSortBoardData();
    if(!GagaSortPathBuilder.TryExpandForWaterPipeVisual(b.PathNodes,b.PathNodeCurves,b.PathNodeElevationCurves,b.PathNodeElevations,b.LoopMode,radius,board.WaterPipeVisualPathPositions,board.WaterPipeVisualPathElevations,out var err))throw new Exception(err);
    var path=new List<Vector3>();GagaSortWaterPipePathUtility.BuildVisualCellPositions(board,new GagaSortBeltData{LoopMode=b.LoopMode},path);path=path.Select(v=>new Vector3(v.x,v.y,-v.z)).ToList();bool closed=b.LoopMode==EGagaSortBeltLoopMode.ClosedPath;
    sources.Add(Analyze("dynamic",path,closed,settings,"production visual expansion"));
    if(recipes.TryGetValue(number,out var entries))foreach(var pair in entries){
     var lib=pair.library;string fp=lib.GetProperty("geometry_fingerprint").GetString();string dbfp=lib.GetProperty("database_fingerprint").GetString();string expected=lib.GetProperty("expected_database_fingerprint").GetString();
     bool geometryMatch=fp==WaterPipeRecipeLibrary.BuildGeometryFingerprint(radius);bool databaseMatch=!string.IsNullOrEmpty(expected)&&string.Equals(dbfp,expected,StringComparison.Ordinal);
     bool entryMatch=lib.GetProperty("database_entries").TryGetProperty(pair.entry.GetProperty("mode").GetInt32().ToString(),out var ids)&&ids.EnumerateArray().Any(v=>v.GetInt32()==number);
     if(geometryMatch&&databaseMatch&&entryMatch)sources.Add(Analyze("recipe",DecodeRecipe(pair.entry),closed,settings,lib.GetProperty("path").GetString(),new{geometry_match=true,database_header_match=true,database_path=lib.GetProperty("database_path").GetString(),database_fingerprint=dbfp,content_fingerprint_recomputed=false,runtime_source_selected=false}));
     else {errors++;sources.Add(new{kind="recipe",source=lib.GetProperty("path").GetString(),status="fingerprint_mismatch",geometry_match=geometryMatch,database_header_match=databaseMatch,entry_match=entryMatch,fingerprint=fp,database_fingerprint=dbfp,expected_database_fingerprint=expected});}
    }
    levels.Add(new{level_id=id,number,sources});
   }catch(Exception e){errors++;levels.Add(new{level_id=id,number,sources,error=e.ToString()});}
   if(levels.Count%100==0)Console.WriteLine("processed="+levels.Count+" errors="+errors);
  }
  File.WriteAllText(args[2],JsonSerializer.Serialize(new{radius,level_count=levels.Count,errors,checks=new[]{"water central strip signed XY area < -1e-5","flat nonadjacent wall-top triangle intersection area > 1e-5; same-side neighbor rows excluded"},levels},new JsonSerializerOptions{DefaultIgnoreCondition=System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull}));Console.WriteLine("levels="+levels.Count+" errors="+errors);
 }
}
