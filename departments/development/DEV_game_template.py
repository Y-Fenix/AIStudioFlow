"""Owned, fixed Android source templates. Model output is data, never executable code."""

DEV_RULES = r'''package studioflow.generated;
import java.util.*;
public final class GameRules {
  public final int[] cards;
  public final boolean[] matched;
  public int first=-1, second=-1, moves=0, found=0;
  public GameRules(int pairs, long seed) {
    cards=new int[pairs*2]; matched=new boolean[pairs*2];
    ArrayList<Integer> deck=new ArrayList<>();
    for(int i=0;i<pairs;i++){deck.add(i);deck.add(i);}
    Collections.shuffle(deck,new Random(seed));
    for(int i=0;i<cards.length;i++)cards[i]=deck.get(i);
  }
  public boolean tap(int index){
    if(index<0 || index>=cards.length || matched[index] || second>=0 || first==index)return false;
    if(first<0){first=index; return true;}
    second=index; moves++;
    if(cards[first]==cards[second]){matched[first]=true;matched[second]=true;found++; first=-1;second=-1;}
    return true;
  }
  public void conceal(){first=-1;second=-1;}
  public boolean won(){return found==cards.length/2;}
}
'''

DEV_RULES_TEST = r'''package studioflow.generated;
public final class GameRulesTest {
  static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
  public static void main(String[] args){
    GameRules game=new GameRules(6,42);
    require(!game.tap(-1),"invalid index");
    int a=0,b=1;while(game.cards[b]==game.cards[a])b++;
    require(game.tap(a),"first tap");require(!game.tap(a),"duplicate tap");
    require(game.tap(b),"mismatch tap");require(game.moves==1,"one move");
    require(!game.tap(3),"blocked until conceal");game.conceal();
    for(int value=0;value<6;value++){
      int first=-1,second=-1;
      for(int i=0;i<game.cards.length;i++)if(game.cards[i]==value){if(first<0)first=i;else second=i;}
      game.tap(first);game.tap(second);require(game.matched[first],"matched pair");
      require(!game.tap(first),"matched card cannot reopen");
    }
    require(game.won(),"victory");require(game.moves==7,"move count");
    require(!new GameRules(6,42).won(),"restart resets");
    System.out.println("PASS: shuffle, tap, mismatch lock, match, victory, restart");
    if(args.length>0)System.out.println("QA_DECK="+java.util.Arrays.toString(new GameRules(Integer.parseInt(args[0]),42).cards));
  }
}
'''

DEV_ACTIVITY = r'''package studioflow.generated;
import android.app.Activity;
import android.os.*;
import android.graphics.*;
import android.view.*;
import android.util.Log;
import org.json.*;
import java.nio.charset.StandardCharsets;

public final class MainActivity extends Activity {
  public void onCreate(Bundle state){super.onCreate(state);getWindow().addFlags(128);setContentView(new Board());}
  final class Board extends View {
    final Paint paint=new Paint(3);
    final Handler timer=new Handler(Looper.getMainLooper());
    GameRules game; String title="Memory Garden", state="ready";
    int pairs=6, seconds=90, accent=Color.rgb(84,180,155);
    long deadline=0; boolean concealPending=false;
    final String[] symbols={"🍎","🍊","🍋","🍇","🍓","🍒","🥝","🍑"};
    Board(){super(MainActivity.this);
      try{byte[] bytes=new byte[getAssets().open("game-spec.json").available()];
        try(java.io.InputStream in=getAssets().open("game-spec.json")){in.read(bytes);}
        JSONObject spec=new JSONObject(new String(bytes,StandardCharsets.UTF_8));
        title=spec.getString("title");pairs=spec.getInt("pairs");seconds=spec.getInt("time_limit_seconds");accent=Color.parseColor(spec.getString("accent_color"));
      }catch(Exception e){throw new IllegalStateException("Invalid game spec",e);}
      setContentDescription(title+" memory matching game");
      timer.post(new Runnable(){public void run(){if(state.equals("playing") && SystemClock.elapsedRealtime()>=deadline){state="lost";Log.i("StudioFlowGame","STATE lost");}invalidate();timer.postDelayed(this,100);}});
      Log.i("StudioFlowGame","STATE ready");
    }
    void start(){game=new GameRules(pairs,getIntent().getLongExtra("qa_seed",System.nanoTime()));deadline=SystemClock.elapsedRealtime()+Math.max(1,getIntent().getIntExtra("qa_seconds",seconds))*1000L;state="playing";concealPending=false;Log.i("StudioFlowGame","STATE playing");invalidate();}
    void label(Canvas c,String text,float x,float y,float size,int color){paint.setColor(color);paint.setTextSize(size);paint.setTextAlign(Paint.Align.CENTER);c.drawText(text,x,y,paint);}
    RectF card(int i){float w=getWidth(),h=getHeight(),gap=w*.025f,cw=(w*.88f-gap*3)/4,ch=Math.min(h*.115f,cw*1.12f);int rows=(pairs*2+3)/4;float top=h*.29f;return new RectF(w*.06f+(i%4)*(cw+gap),top+(i/4)*(ch+gap),w*.06f+(i%4)*(cw+gap)+cw,top+(i/4)*(ch+gap)+ch);}
    protected void onDraw(Canvas c){super.onDraw(c);float w=getWidth(),h=getHeight();c.drawColor(Color.rgb(17,26,39));
      label(c,title,w/2,h*.11f,w*.063f,Color.WHITE);
      label(c,"MEMORY MATCH",w/2,h*.16f,w*.03f,accent);
      if(state.equals("ready")){
        label(c,"Find every matching pair",w/2,h*.40f,w*.047f,Color.WHITE);
        label(c,pairs+" pairs · "+seconds+" seconds",w/2,h*.46f,w*.038f,Color.LTGRAY);
        label(c,"Tap two cards. Remember the pictures.",w/2,h*.53f,w*.035f,Color.LTGRAY);
      }else{
        int remaining=(int)Math.max(0,(deadline-SystemClock.elapsedRealtime()+999)/1000);
        label(c,"Time "+remaining+"s    Moves "+game.moves+"    "+game.found+"/"+pairs,w/2,h*.23f,w*.036f,Color.WHITE);
        for(int i=0;i<game.cards.length;i++){RectF r=card(i);boolean open=game.matched[i]||game.first==i||game.second==i;
          paint.setColor(game.matched[i]?Color.rgb(36,91,78):open?Color.rgb(240,238,225):Color.rgb(43,60,79));c.drawRoundRect(r,14,14,paint);
          label(c,open?symbols[game.cards[i]]:"?",r.centerX(),r.centerY()+r.height()*.16f,r.width()*.43f,accent);
        }
        if(state.equals("won")||state.equals("lost")){paint.setColor(0xDF111A27);c.drawRect(0,h*.36f,w,h*.65f,paint);label(c,state.equals("won")?"You won!":"Time is up",w/2,h*.48f,w*.08f,Color.WHITE);label(c,"Moves: "+game.moves,w/2,h*.55f,w*.045f,accent);}
      }
      paint.setColor(accent);c.drawRoundRect(w*.18f,h*.83f,w*.82f,h*.92f,20,20,paint);
      label(c,state.equals("ready")?"START":"RESTART",w/2,h*.888f,w*.05f,Color.rgb(17,26,39));
    }
    public boolean onTouchEvent(MotionEvent event){if(event.getAction()!=MotionEvent.ACTION_UP)return true;float x=event.getX(),y=event.getY();
      if(x>=getWidth()*.18f&&x<=getWidth()*.82f&&y>=getHeight()*.83f&&y<=getHeight()*.92f){start();return true;}
      if(!state.equals("playing")||SystemClock.elapsedRealtime()>=deadline)return true;
      for(int i=0;i<game.cards.length;i++)if(card(i).contains(x,y)&&game.tap(i)){
        Log.i("StudioFlowGame","TAP index="+i+" moves="+game.moves+" pairs="+game.found);
        if(game.won()){state="won";Log.i("StudioFlowGame","STATE won");}
        else if(game.second>=0&&!concealPending){concealPending=true;final GameRules current=game;timer.postDelayed(new Runnable(){public void run(){if(game==current){game.conceal();concealPending=false;invalidate();}}},650);}
        invalidate();break;
      }return true;
    }
    protected void onDetachedFromWindow(){timer.removeCallbacksAndMessages(null);super.onDetachedFromWindow();}
  }
}
'''
