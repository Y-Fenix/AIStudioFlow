import unittest
from departments.development.DEV_game_builder import DEV_normalize_spec

class DEV_LoopGameTests(unittest.TestCase):
    def test_loop_spec_is_not_silently_converted_to_memory(self):
        spec=DEV_normalize_spec({'game_type':'loop','title':'Loop Garden'})
        self.assertEqual(spec['game_type'],'loop')
        self.assertEqual(spec['title'],'Loop Garden')
        self.assertNotIn('pairs',spec)
        self.assertEqual(spec['levels'],1000)

    def test_loop_content_boundaries_and_hint_move_semantics_on_jvm(self):
        import tempfile,subprocess,shutil
        from pathlib import Path
        from departments.development.DEV_loop_template import DEV_LOOP_RULES
        if not shutil.which('javac'):self.skipTest('JDK unavailable')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'studioflow/generated';source.mkdir(parents=True)
            (source/'GameRules.java').write_text(DEV_LOOP_RULES)
            (source/'ContractTest.java').write_text('''package studioflow.generated;
public class ContractTest {public static void main(String[] args){
if(new GameRules(100).size!=4||new GameRules(101).size!=5||new GameRules(400).size!=5||new GameRules(401).size!=6)throw new AssertionError("size boundaries");
GameRules.InputGate gate=new GameRules.InputGate();gate.transition(1000);if(gate.accept(1100)||!gate.accept(1500))throw new AssertionError("transition residual input");
GameRules empty=new GameRules(1);java.util.Arrays.fill(empty.cells,0);if(empty.solved())throw new AssertionError("empty board must not win");
GameRules g=new GameRules(1);g.hint();if(g.moves!=0||g.hints!=1)throw new AssertionError("hint must not increase moves");
java.util.Set<String> seen=new java.util.HashSet<String>();
for(int level=1;level<=1000;level++){GameRules content=new GameRules(level);if(!seen.add(content.size+java.util.Arrays.toString(content.cells)))throw new AssertionError("duplicate initial layout "+level);}
for(int level=1;level<=1000;level++)for(int m:new GameRules(level).cells)if(Integer.bitCount(m)!=0&&Integer.bitCount(m)!=2)throw new AssertionError("only curves and straights");
try{new GameRules(1001);throw new AssertionError("level overflow");}catch(IllegalArgumentException expected){}
}}''')
            subprocess.run(['javac','-d',str(root),str(source/'GameRules.java'),str(source/'ContractTest.java')],check=True,capture_output=True)
            subprocess.run(['java','-cp',str(root),'studioflow.generated.ContractTest'],check=True,capture_output=True)
