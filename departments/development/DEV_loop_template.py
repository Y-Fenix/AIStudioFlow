"""Offline loop puzzle sources. No external artwork or network dependencies."""
DEV_LOOP_RULES = r'''package studioflow.generated;
import java.util.Random;
public class GameRules {
 public static class InputGate { private long blockedUntil; public void transition(long now){blockedUntil=now+400;} public boolean accept(long now){return now>=blockedUntil;} }
 public int size; public long moves, hints; public int[] cells, solution;
 public static int rotate(int m) { return ((m<<1)&15)|(m>>3); }
 public GameRules(int level) {
  if(level<1||level>1000)throw new IllegalArgumentException("level outside 1..1000");
  size=level<=100?4:level<=400?5:6; cells=new int[size*size]; solution=new int[cells.length];
  Random rng=new Random(8171L+level*997L);
  // Disjoint rectangle rings keep every occupied tile a straight or curve.
  for(int k=0;k<24;k++) {
   int x=rng.nextInt(size-1), y=rng.nextInt(size-1);
   int right=x+1+rng.nextInt(size-1-x), bottom=y+1+rng.nextInt(size-1-y);
   boolean free=true;
   for(int r=y;r<=bottom;r++)for(int c=x;c<=right;c++)if((r==y||r==bottom||c==x||c==right)&&solution[r*size+c]!=0)free=false;
   if(!free)continue;
   for(int c=x;c<right;c++){edge(y*size+c,y*size+c+1,2,8);edge(bottom*size+c,bottom*size+c+1,2,8);}
   for(int r=y;r<bottom;r++){edge(r*size+x,(r+1)*size+x,4,1);edge(r*size+right,(r+1)*size+right,4,1);}
  }
  boolean any=false;for(int m:solution)if(m!=0)any=true;
  if(!any){edge(0,1,2,8);edge(1,size+1,4,1);edge(size+1,size,8,2);edge(size,0,1,4);}
  for(int i=0;i<cells.length;i++){cells[i]=solution[i];for(int j=rng.nextInt(4);j>0;j--)cells[i]=rotate(cells[i]);}
  if(solved())for(int i=0;i<cells.length;i++)if(cells[i]!=0&&cells[i]!=15){cells[i]=rotate(cells[i]);break;}
 }
 private void edge(int a,int b,int ma,int mb){solution[a]^=ma;solution[b]^=mb;}
 public void turn(int i){if(i>=0&&i<cells.length&&cells[i]!=0){cells[i]=rotate(cells[i]);if(moves<Long.MAX_VALUE)moves++;}}
 public boolean connected(int i,int d){
  int x=i%size,y=i/size;int[] dx={0,1,0,-1},dy={-1,0,1,0};
  int nx=x+dx[d],ny=y+dy[d];return nx>=0&&ny>=0&&nx<size&&ny<size&&(cells[ny*size+nx]&(1<<((d+2)%4)))!=0;
 }
 public boolean solved(){boolean occupied=false;for(int m:cells)if(m!=0)occupied=true;if(!occupied)return false;for(int i=0;i<cells.length;i++)for(int d=0;d<4;d++)if((cells[i]&(1<<d))!=0&&!connected(i,d))return false;return true;}
 public void hint(){if(solved())return;for(int i=0;i<cells.length;i++)if(cells[i]!=solution[i]){cells[i]=solution[i];if(hints<Long.MAX_VALUE)hints++;return;}}
}'''
DEV_LOOP_TEST = r'''package studioflow.generated;
public class GameRulesTest {
 public static void main(String[] args){
  StringBuilder records=new StringBuilder("[\n");java.util.Set<String> seen=new java.util.HashSet<String>();
  for(int level=1;level<=1000;level++){
   GameRules g=new GameRules(level);
   String initial=java.util.Arrays.toString(g.cells);
   if(!seen.add(g.size+initial))throw new AssertionError("duplicate initial board "+level);
   if(g.solved())throw new AssertionError("scramble already solved "+level);
   for(int i=0;i<g.cells.length;i++){
    int original=g.cells[i];for(int r=0;r<4;r++)g.turn(i);
    if(g.cells[i]!=original)throw new AssertionError("rotation");
   }
   for(int i=0;i<g.cells.length;i++){int count=0;while(g.cells[i]!=g.solution[i]&&count++<4)g.turn(i);}
   if(!g.solved())throw new AssertionError("unsolvable "+level);
   GameRules h=new GameRules(level);for(int i=0;i<h.cells.length;i++)h.hint();
   if(!h.solved())throw new AssertionError("hint");
   if(level>1)records.append(",\n");
   records.append("{\"level\":").append(level).append(",\"size\":").append(g.size).append(",\"initial\":").append(initial).append(",\"target\":").append(java.util.Arrays.toString(g.solution)).append(",\"rotation_checked\":true,\"solvable\":true,\"hint_checked\":true}");
  }
  records.append("\n]");if(args.length>1)try{java.nio.file.Files.write(java.nio.file.Paths.get(args[1]),records.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}catch(java.io.IOException e){throw new RuntimeException(e);}
  System.out.println("QA_LOOP_FIRST="+java.util.Arrays.toString(new GameRules(1).cells));
  System.out.println("LOOP_RULES_PASS levels=1000 rotation solvability hints");
 }
}'''
DEV_LOOP_ACTIVITY = r'''package studioflow.generated;
import android.app.Activity;
import android.app.AlertDialog;
import org.json.*;
import java.util.*;
import android.widget.Toast;
import android.os.Bundle;
import android.graphics.*;
import android.view.*;
import android.content.*;
import android.util.Log;
public class MainActivity extends Activity {
 boolean incompatible=false; String gameTitle="Loop Garden"; int level=1; GameRules game; Board board; Set<Integer> completed=new HashSet<Integer>();
 public void onCreate(Bundle b){super.onCreate(b);getWindow().setFlags(1024,1024);game=new GameRules(1);
  try{java.io.InputStream input=getAssets().open("game-spec.json");java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();byte[] buffer=new byte[1024];int n;while((n=input.read(buffer))!=-1)bytes.write(buffer,0,n);input.close();gameTitle=new JSONObject(bytes.toString("UTF-8")).optString("title","Loop Garden");}catch(Exception ignored){}
  String state=getPreferences(0).getString("state","");try{incompatible=!state.isEmpty()&&new JSONObject(state).optInt("version",-1)!=1;}catch(Exception ignored){}
  if(!incompatible&&!restore(state)){if(restore(getPreferences(0).getString("backup","")))Toast.makeText(this,"Recovered previous saved board. Recent changes may be missing.",Toast.LENGTH_LONG).show();else if(!state.isEmpty())Toast.makeText(this,"Saved board was invalid. Starting a new garden.",Toast.LENGTH_LONG).show();}
  board=new Board(this);setContentView(board);
  if(incompatible)new AlertDialog.Builder(this).setTitle("Newer save format").setMessage("This save is not compatible. It will be preserved until you explicitly start a new garden.").setCancelable(false).setNegativeButton("Exit",new DialogInterface.OnClickListener(){public void onClick(DialogInterface d,int w){finish();}}).setPositiveButton("Start new garden",new DialogInterface.OnClickListener(){public void onClick(DialogInterface d,int w){getPreferences(0).edit().putString("incompatible_archive",getPreferences(0).getString("state","")).commit();incompatible=false;save();}}).show();Log.i("StudioFlowGame","LOOP ready level="+level+" moves="+game.moves+" hints="+game.hints);
  if(!getPreferences(0).getBoolean("introduced",false))new AlertDialog.Builder(this).setTitle("Welcome to Loop Garden").setMessage("Tap a pipe to rotate it clockwise. Connect every open end. Multiple loops are welcome. Hint adjusts one tile toward a solution; it does not cost a move. Your board saves automatically.").setPositiveButton("Got it",new DialogInterface.OnClickListener(){public void onClick(DialogInterface d,int w){getPreferences(0).edit().putBoolean("introduced",true).commit();}}).show();
 }
 boolean restore(String text){try{
  JSONObject s=new JSONObject(text);if(s.getInt("version")!=1)return false;
  int l=s.getInt("level");GameRules g=new GameRules(l);JSONArray cells=s.getJSONArray("cells");
  if(cells.length()!=g.cells.length)return false;
  for(int i=0;i<g.cells.length;i++){int value=cells.getInt(i),candidate=g.solution[i];boolean valid=false;for(int k=0;k<4;k++){if(value==candidate)valid=true;candidate=GameRules.rotate(candidate);}if(!valid)return false;g.cells[i]=value;}
  g.moves=s.getLong("moves");g.hints=s.getLong("hints");if(g.moves<0||g.hints<0)return false;
  Set<Integer> done=new HashSet<Integer>();JSONArray a=s.getJSONArray("completed");for(int i=0;i<a.length();i++){int v=a.getInt(i);if(v<1||v>1000)return false;done.add(v);}
  level=l;game=g;completed=done;return true;
 }catch(Exception e){return false;}}
 boolean save(){if(incompatible)return false;try{
  JSONObject s=new JSONObject();s.put("version",1);s.put("level",level);s.put("moves",game.moves);s.put("hints",game.hints);JSONArray a=new JSONArray();for(int value:game.cells)a.put(value);s.put("cells",a);a=new JSONArray();for(int value:completed)a.put(value);s.put("completed",a);
  String old=getPreferences(0).getString("state","");boolean ok=getPreferences(0).edit().putString("backup",old).putString("state",s.toString()).commit();
  if(!ok){restore(old);if(board!=null)board.won=game.solved();Toast.makeText(this,"Could not save. Previous board restored.",Toast.LENGTH_LONG).show();}return ok;
 }catch(Exception e){Toast.makeText(this,"Save unavailable",Toast.LENGTH_LONG).show();return false;}}
 protected void onPause(){save();super.onPause();}
 void levels(){String[] names=new String[1000];int unlocked=1;while(unlocked<1000&&completed.contains(unlocked))unlocked++;final int limit=unlocked;
  for(int i=0;i<1000;i++)names[i]="Level "+(i+1)+(completed.contains(i+1)?"  ✓":i+1>limit?"  🔒 Locked":"");
  new AlertDialog.Builder(this).setTitle("Your garden · "+completed.size()+" / 1000").setItems(names,new DialogInterface.OnClickListener(){public void onClick(DialogInterface d,int which){if(which+1>limit){Toast.makeText(MainActivity.this,"Complete earlier levels first",Toast.LENGTH_SHORT).show();return;}final int selected=which+1;new AlertDialog.Builder(MainActivity.this).setTitle("Open level "+selected+"?").setMessage("The current attempt will be replaced. Completed levels are kept.").setNegativeButton("Cancel",null).setPositiveButton("Open",new DialogInterface.OnClickListener(){public void onClick(DialogInterface d,int w){level=selected;game=new GameRules(level);board.won=false;save();board.invalidate();Log.i("StudioFlowGame","LOOP choose level="+level);}}).show();}}).setNegativeButton("Close",null).show();
 }
 class Board extends View {
  Paint p=new Paint(3);float ox,oy,cell,w,h; int ink=Color.rgb(44,83,78),teal=Color.rgb(38,148,130);boolean won=false;long start=System.currentTimeMillis();GameRules.InputGate gate=new GameRules.InputGate();int highlighted=-1;
  Board(Context c){super(c);won=game.solved();setContentDescription("Loop puzzle. Tap pipes to rotate. Use Hint or Restart below. Level "+level);setLayerType(View.LAYER_TYPE_SOFTWARE,null);}
  void text(Canvas c,String s,float x,float y,float z,int color){p.setColor(color);p.setTextSize(z);p.setTypeface(Typeface.create("sans-serif",Typeface.NORMAL));p.setTextAlign(Paint.Align.CENTER);p.setStyle(Paint.Style.FILL);c.drawText(s,x,y,p);}
  void button(Canvas c,String s,float x,float y,float ww,boolean primary){p.setColor(primary?teal:Color.rgb(227,236,229));p.setStyle(Paint.Style.FILL);c.drawRoundRect(x-ww/2,y-25,x+ww/2,y+25,18,18,p);text(c,s,x,y+6,16,primary?Color.WHITE:ink);}
  protected void onDraw(Canvas raw){
   super.onDraw(raw);float scale=getWidth()/400f;raw.save();raw.scale(scale,scale);Canvas c=raw;w=400;h=getHeight()/scale;
   c.drawColor(Color.rgb(246,247,240));
   text(c,gameTitle.toUpperCase(java.util.Locale.ROOT),200,65,Math.min(16,560f/Math.max(1,gameTitle.length())),teal);text(c,"Find your flow.",200,110,32,ink);
   text(c,"LEVEL "+String.format("%02d",level)+"    /    "+(game.moves>999999?"999999+":game.moves)+" MOVES   /   "+(game.hints>999999?"999999+":game.hints)+" HINTS",200,148,13,Color.rgb(116,133,123));
   text(c,"LEVELS  ↗",340,177,12,teal);cell=344f/game.size;ox=28;oy=Math.max(180,(h-game.size*cell)/2-10);
   for(int i=0;i<game.cells.length;i++){
    float x=ox+(i%game.size+.5f)*cell,y=oy+(i/game.size+.5f)*cell;int m=game.cells[i];
    p.setStyle(Paint.Style.FILL);p.setColor(i==highlighted?Color.rgb(204,226,210):Color.rgb(237,241,232));c.drawCircle(x,y,cell*.40f,p);
    p.setStrokeWidth(cell*.09f);p.setStrokeCap(Paint.Cap.ROUND);
    for(int d=0;d<4;d++)if((m&(1<<d))!=0){p.setColor(game.connected(i,d)?teal:ink);float[] dx={0,1,0,-1},dy={-1,0,1,0};c.drawLine(x,y,x+dx[d]*cell*.5f,y+dy[d]*cell*.5f,p);}
    if(m!=0){p.setColor(teal);c.drawCircle(x,y,cell*.065f,p);}
   }
   if(won){text(c,"Beautifully connected.",200,oy+game.size*cell+42,23,teal);button(c,level<1000?"NEXT LEVEL  →":"LEVEL LIST  ✓",200,h-65,260,true);}
   else {text(c,"Tap to rotate. Close every open end.",200,oy+game.size*cell+38,13,Color.rgb(116,133,123));button(c,"RESTART",110,h-65,140,false);button(c,"HINT",290,h-65,140,true);}
   raw.restore();
  }
  public boolean onTouchEvent(android.view.MotionEvent e){
   if(e.getAction()!=MotionEvent.ACTION_UP)return true;if(incompatible||!gate.accept(android.os.SystemClock.uptimeMillis()))return true;float scale=getWidth()/400f,x=e.getX()/scale,y=e.getY()/scale;
   if(y>155&&y<193&&x>280){levels();return true;}
   if(y>h-95&&y<h-35){if(won){if(level==1000){levels();return true;}gate.transition(android.os.SystemClock.uptimeMillis());level++;game=new GameRules(level);won=false;save();Log.i("StudioFlowGame","LOOP next level="+level);}else if(x<200){new AlertDialog.Builder(MainActivity.this).setTitle("Restart this level?").setMessage("This attempt and its moves will reset. Completed levels are kept.").setNegativeButton("Cancel",null).setPositiveButton("Restart",new DialogInterface.OnClickListener(){public void onClick(DialogInterface d,int which){game=new GameRules(level);won=false;save();invalidate();Log.i("StudioFlowGame","LOOP restart");}}).show();return true;}else{highlighted=-1;for(int j=0;j<game.cells.length;j++)if(game.cells[j]!=game.solution[j]){highlighted=j;break;}game.hint();Log.i("StudioFlowGame","LOOP hint");}}
   else if(!won&&x>=ox&&x<ox+game.size*cell&&y>=oy&&y<oy+game.size*cell){int i=(int)((y-oy)/cell)*game.size+(int)((x-ox)/cell);game.turn(i);performHapticFeedback(1);Log.i("StudioFlowGame","LOOP turn="+i);}
   if(game.solved()&&!won){won=true;completed.add(level);Log.i("StudioFlowGame","LOOP won level="+level);}
   save();
   invalidate();return true;
  }
 }
}'''
