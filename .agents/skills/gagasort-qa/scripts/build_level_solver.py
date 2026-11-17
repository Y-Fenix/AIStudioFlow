#!/usr/bin/env python3
"""Compile production solver and DifficultyEvaluator outside Editor, with fresh replay proofs.

Input: {levels:[{level_id:string,raw_record:[complete MessagePack Key-array]}],
logic_config?:{longest GagaSortLogicConfig constructor parameter names:values}}.
Absent logic_config is read from the shipped GameConfig asset and its BreakClip.
No Player/Editor launch and no production source/asset writes.
"""
import argparse, difflib, hashlib, json, re, subprocess, sys
from pathlib import Path


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def block_end(source, begin):
    depth = 1
    pos = begin + 1
    while depth:
        depth += (source[pos] == '{') - (source[pos] == '}')
        pos += 1
    return pos


def read_config(repo):
    asset = repo / 'GagaSort/Assets/Resources/GagaSort/Config/GagaSortGameConfig.asset'
    text = asset.read_text()
    def number(path):
        parts = path.split('.')
        section = text
        indent = '  '
        for part in parts[:-1]:
            match = re.search(r'^' + indent + re.escape(part) + r':\s*\n(.*?)(?=^' + indent + r'\S|\Z)', section, re.M | re.S)
            if not match:
                raise ValueError('Missing shipped config section: ' + path)
            section = match[1]
            indent += '  '
        found = re.findall(r'^' + indent + re.escape(parts[-1]) + r':\s*([-+\d.eE]+)\s*$', section, re.M)
        if len(found) != 1:
            raise ValueError('Missing/ambiguous shipped scalar: ' + path)
        return float(found[0])
    mapping = '''portalPathLengthCells TransferAnimation.PortalPathLengthCells
slotCoverUnlockDurationSeconds PadlockAnimation.UnlockDurationSeconds
iceMeltDurationSeconds Ice.IceMeltDurationSeconds
refreshBoosterDurationSeconds BoosterAnimation.RefreshBoosterDurationSeconds
removeBoosterItemDurationSeconds BoosterAnimation.RemoveBoosterItemDurationSeconds
beltMoveCellsPerSecond BeltMoveCellsPerSecond
autoCompleteSpeedMultiplier AutoCompleteSpeedMultiplier
rightAngleCornerRadiusCells PathGeometry.RightAngleCornerRadiusCells
transparentNumberPackageUnlockDurationSeconds SlotPackageAnimation.TransparentNumberPackageUnlockDurationSeconds
colorPackageUnlockDurationSeconds SlotPackageAnimation.ColorPackageUnlockDurationSeconds
opaqueNumberPackageUnlockDurationSeconds SlotPackageAnimation.OpaqueNumberPackageUnlockDurationSeconds
poolQueueAdvanceDurationSeconds TransferAnimation.PoolQueueAdvanceDurationSeconds
poolQueueFollowDelaySeconds TransferAnimation.PoolQueueFollowDelaySeconds
padlockKeyFlightSpeedCellsPerSecond PadlockAnimation.KeyFlightSpeedCellsPerSecond
releaseReservationDistanceFactor TransferAnimation.ReleaseReservationDistanceFactor
releaseReservationBaseDistanceCells TransferAnimation.ReleaseReservationBaseDistanceCells
nonFirstReleaseApproachTimeWeight TransferAnimation.NonFirstReleaseApproachTimeWeight
nonFirstReleaseEntryTimeWeight TransferAnimation.NonFirstReleaseEntryTimeWeight
releaseFirstApproachStaggerRatio TransferAnimation.ReleaseFirstApproachStaggerRatio
poolQueueRampRatio TransferAnimation.PoolQueueRampRatio
firstReleaseApproachTimeWeight TransferAnimation.FirstReleaseApproachTimeWeight
firstReleaseEntryTimeWeight TransferAnimation.FirstReleaseEntryTimeWeight
beltSpeedReferenceSpacingCells BeltSpeedReferenceSpacingCells
beltSpacingMaxSpeedMultiplier BeltSpacingMaxSpeedMultiplier
beltSpeedFullSpacingCells BeltSpeedFullSpacingCells
crystalShatterDurationSeconds GlassAnimation.ShatterDurationSeconds
cloakRevealDurationSeconds CloakAnimation.RevealDurationSeconds
channelBlockUnlockDurationSeconds ChannelBlockVisual.UnlockDurationSeconds
cloakRopeUnlockDurationSeconds CloakAnimation.RopeUnlockDurationSeconds
nonFirstReleasePredecessorClearanceCells TransferAnimation.NonFirstReleasePredecessorClearanceCells
pickaxeFlightDurationSeconds StonePickaxe.FlightDurationSeconds
pickaxeStrikeDurationSeconds StonePickaxe.StrikeDurationSeconds
stoneBreakDurationSeconds StonePickaxe.BreakDurationSeconds
blockingEmitterOpenDurationSeconds PoolMechanismVisuals.BlockingEmitterOpenDurationSeconds
activationPackageUnlockDurationSeconds PoolMechanismVisuals.ActivationPackageUnlockDurationSeconds'''
    config = {key: number(path) for key, path in (line.split() for line in mapping.splitlines())}
    config['cloakRopeRevealDurationSeconds'] = number('CloakAnimation.RopeUnlockDurationSeconds') + max(number('CloakAnimation.RevealDurationSeconds'), number('CloakAnimation.RopeRelockDelaySeconds') + number('CloakAnimation.RopeRelockDurationSeconds'))
    config['questionRevealDurationSeconds'] = number('Question.SpriteShrinkDurationSeconds') + number('Question.DissolveDurationSeconds')
    styles = re.search(r'^  DuckStyles:\n(.*?)(?=^  \w|\Z)', text, re.M | re.S)[1]
    config['enabledDuckColors'] = [int(x) for x in re.findall(r'^  - Color: (\d+)', styles, re.M) if int(x) != 19]
    # Resolve the exact prefab and clip by GUID, rather than assuming a resource filename.
    metas = None
    def resolve_guid(guid):
        nonlocal metas
        if metas is None:
            metas = list((repo / 'GagaSort/Assets').rglob('*.meta'))
        matches = [p.with_suffix('') for p in metas if re.search(r'^guid: ' + guid + '$', p.read_text(errors='replace'), re.M)]
        if len(matches) != 1:
            raise ValueError('GUID resolution failed: ' + guid)
        return matches[0]
    prefab_guid = re.search(r'^  ConnectionVisualPrefab:.*guid: ([a-f0-9]+)', text, re.M)
    sources = [asset, repo / 'GagaSort/Assets/Scripts/GamePlay/GagaSort/Runtime/Config/GagaSortGameConfig.cs', repo / 'GagaSort/Assets/Scripts/GamePlay/GagaSort/Runtime/Config/GagaSortMechanismVisualConfig.cs']
    if prefab_guid:
        prefab = resolve_guid(prefab_guid[1]); sources.append(prefab)
        clip_guid = re.search(r'^  BreakClip:.*guid: ([a-f0-9]+)', prefab.read_text(), re.M)
        if not clip_guid:
            raise ValueError('BreakClip missing on configured prefab')
        clip = resolve_guid(clip_guid[1]); sources.append(clip)
        clip_text = clip.read_text()
        start = float(re.search(r'^    m_StartTime: ([\d.eE+-]+)', clip_text, re.M)[1])
        stop = float(re.search(r'^    m_StopTime: ([\d.eE+-]+)', clip_text, re.M)[1])
        config['connectionBreakDurationSeconds'] = stop - start
    else:
        raise ValueError('No configured ConnectionVisualPrefab; explicit logic_config required')
    return config, sources


def instrument_solver(source):
    # Observational additions only. The production heap, priorities, branching,
    # snapshots, budgets and all transition calls remain unchanged.
    source = source.replace('private readonly List<int> mClickableSlotIds', '''public List<int[]> TraceActions { get; private set; } = new();
        public int TraceEndFrame { get; private set; }
        private readonly Dictionary<GagaSortSearchSnapshot, List<int[]>> mTraceBySnapshot = new();
        private List<int[]> mCurrentTrace = new();
        private readonly List<int> mClickableSlotIds''', 1)
    source = source.replace('var stopwatch = Stopwatch.StartNew();', 'TraceActions = new(); TraceEndFrame = 0; mTraceBySnapshot.Clear(); mCurrentTrace = new();\n            var stopwatch = Stopwatch.StartNew();', 1)
    source = source.replace('var node = frontier.Dequeue();', 'var node = frontier.Dequeue();\n                var baseTrace = mTraceBySnapshot[node.Snapshot];\n                mCurrentTrace = new(baseTrace); mTraceBySnapshot.Remove(node.Snapshot);', 1)
    source = source.replace('runtime.EnqueueCommand(new GagaSortClickSlotCommand(slotId, runtime.CurrentFrameId));', 'mCurrentTrace = new(baseTrace);\n                    mCurrentTrace.Add(new[] { node.Depth + 1, slotId });\n                    runtime.EnqueueCommand(new GagaSortClickSlotCommand(slotId, runtime.CurrentFrameId));', 1)
    source = source.replace('if (node.Snapshot.HasFutureDynamics()) {', 'if (node.Snapshot.HasFutureDynamics()) {\n                    mCurrentTrace = new(baseTrace);', 1)
    for terminal_frame in ['1', 'node.Depth + 2', 'node.Depth + 2', 'node.Depth + forcedFrameCount + 1']:
        source = source.replace('if (model.HasCompleted) {', 'if (model.HasCompleted /* recorded */) {\n                    TraceActions = new(mCurrentTrace); TraceEndFrame = ' + terminal_frame + ';', 1)
    source = source.replace('private static void EnqueueSnapshot(', 'private void EnqueueSnapshot(', 1)
    source = source.replace('bestDepthByState[stateKey] = depth;', 'mTraceBySnapshot[snapshot] = new(mCurrentTrace);\n            bestDepthByState[stateKey] = depth;', 1)
    return source


def instrument_evaluator(source):
    # Trace only the real attempt, never its cloned planning simulations.
    edits = [
        ('public sealed class GagaSortDifficultyEvaluator {', '''public sealed class GagaSortDifficultyEvaluator {
        public List<int[]> TraceActions { get; private set; } = new();
        public int TraceEndFrame { get; private set; }'''),
        ('using var logScope = GagaSortLevelRuntimeDiagnostics.SuppressSimulationLogs();',
         'TraceActions = new(); TraceEndFrame = 0;\n            using var logScope = GagaSortLevelRuntimeDiagnostics.SuppressSimulationLogs();'),
        ('return state.ToResult(EGagaSortDifficultyAttemptStatus.Passed, options.BeltCapacity);',
         'TraceEndFrame = runtime.CurrentFrameId;\n                        return state.ToResult(EGagaSortDifficultyAttemptStatus.Passed, options.BeltCapacity);'),
        ('runtime.EnqueueCommand(new GagaSortClickSlotCommand(\n                selected.SlotId,',
         'TraceActions.Add(new[] { runtime.CurrentFrameId, selected.SlotId });\n            runtime.EnqueueCommand(new GagaSortClickSlotCommand(\n                selected.SlotId,')]
    for before, after in edits:
        if source.count(before) != 1:
            raise ValueError('Evaluator trace site missing/ambiguous: ' + before)
        source = source.replace(before, after, 1)
    return source


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for flag in ['repo', 'input', 'output', 'build-dir']:
        ap.add_argument('--' + flag, type=Path, required=True)
    ap.add_argument('--kernel-dir', type=Path)
    ap.add_argument('--time-ms', type=int, default=200)
    ap.add_argument('--max-nodes', type=int, default=50000)
    ap.add_argument('--max-frames', type=int, default=250000)
    ap.add_argument('--max-levels', type=int, default=0)
    ap.add_argument('--aux-time-ms', type=int, default=300,
                    help='Total cooperative budget for production evaluator fallback; 0 disables')
    ap.add_argument('--aux-attempt-time-ms', type=int, default=150)
    opt = ap.parse_args()
    if min(opt.time_ms, opt.max_nodes, opt.max_frames, opt.aux_attempt_time_ms) <= 0 or min(opt.max_levels, opt.aux_time_ms) < 0:
        ap.error('budgets must be positive; max-levels must be nonnegative')
    repo = opt.repo.resolve(); root = opt.build_dir.resolve(); root.mkdir(parents=True, exist_ok=True)
    project = repo / 'GagaSort'; base = project / 'Assets/Scripts/GamePlay/GagaSort/Runtime'
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    data = json.loads(opt.input.read_text()); config_sources = []
    if 'logic_config' not in data:
        data['logic_config'], config_sources = read_config(repo)
    if opt.max_levels:
        data['levels'] = data['levels'][:opt.max_levels]
    effective = root / 'effective-input.json'; effective.write_text(json.dumps(data, ensure_ascii=False))
    version = (project / 'ProjectSettings/ProjectVersion.txt').read_text().splitlines()[0].split(':', 1)[1].strip()
    unity = Path('/Applications/Unity/Hub/Editor') / version / 'Unity.app/Contents'
    runtime = sorted((unity / 'NetCoreRuntime/shared/Microsoft.NETCore.App').glob('6.*'), key=lambda p: tuple(map(int,p.name.split('.'))))[-1]
    dotnet = unity / 'NetCoreRuntime/dotnet'; csc = unity / 'DotNetSdkRoslyn/csc.dll'
    kernel = (opt.kernel_dir or root / 'kernel').resolve()
    manifest_path = kernel / 'manifest.json'
    valid = manifest_path.exists()
    if valid:
        km = json.loads(manifest_path.read_text())
        valid = all(Path(s['path']).exists() and digest(Path(s['path'])) == s['sha256'] for s in km['sources'])
    if not valid:
        empty = root / 'empty-geometry.json'; empty.write_text('{"levels":[]}')
        subprocess.run([sys.executable, str(Path(__file__).with_name('build_level_splines.py')), '--repo', str(repo), '--build-dir', str(kernel), '--input', str(empty), '--output', str(root/'empty-geometry-result.json'), '--radius', '2.5'], check=True, cwd=repo)
    manifest = {'repo':str(repo), 'head':head, 'input_sha256':digest(opt.input), 'effective_input_sha256':digest(effective), 'kernel_manifest_sha256':digest(manifest_path), 'sources':[], 'adaptations':[], 'boundaries':['No UNITY_EDITOR/DEBUG; no Editor/Player/asset writes.', 'Only ScriptableObject Validator overloads excluded from temporary compile closure; pure logic Validator unchanged.', 'Solver path recording only; original Runtime independently replays every successful path.', 'No boosters/unlock/paid Extra actions; unknown budget result remains Inconclusive.']}
    def adapt(path, value, name):
        target = root / name; target.write_text(value)
        diff = root / (name + '.diff')
        diff.write_text(''.join(difflib.unified_diff(path.read_text().splitlines(True), value.splitlines(True), fromfile=str(path), tofile=str(target))))
        manifest['adaptations'].append({'source':str(path), 'sha256':digest(path), 'diff':str(diff),'diff_sha256':digest(diff)})
        return target
    sources = sorted((base/'Data').glob('*.cs')) + sorted((base/'Logic').rglob('*.cs')) + sorted((base/'Level').glob('*.cs'))
    validator = base / 'Level/GagaSortLevelValidator.cs'; text = validator.read_text()
    for match in reversed(list(re.finditer(r'public\s+[\w<>]+\s+\w+\([^)]*GagaSortGameConfig gameConfig\)\s*\{', text))):
        end = block_end(text, text.index('{', match.start()))
        text = text[:match.start()] + text[end:]
    replacements = {validator:adapt(validator, text, 'GagaSortLevelValidator.Headless.cs')}
    solver = base / 'Logic/Solver/GagaSortSolvabilitySolver.cs'
    replacements[solver] = adapt(solver, instrument_solver(solver.read_text()), 'GagaSortSolvabilitySolver.Traced.cs')
    evaluator = base / 'Logic/Difficulty/GagaSortDifficultyEvaluator.cs'
    replacements[evaluator] = adapt(evaluator, instrument_evaluator(evaluator.read_text()), 'GagaSortDifficultyEvaluator.Traced.cs')
    manifest['boundaries'] += ['Only Inconclusive search results use the original production DifficultyEvaluator (Novice/Typical, fixed seed, single worker).', 'Evaluator trace additions only; failed attempts cannot establish Unsolvable. Auxiliary budgets use cooperative cancellation; replay time is included in actual elapsed time.']
    sources = [replacements.get(p,p) for p in sources]
    sources += [base/'Config/GagaSortBoosterVisualConfig.cs', base/'Feedback/GagaSortFeedbackEventMapper.cs', base/'Config/GagaSortLogicConfig.cs', base/'Config/GagaSortPresentationConfig.cs',base/'Hotfix/GagaSortLevelRuntimeDiagnostics.cs', project/'Assets/Scripts/GamePlay/Gameplay/Contracts/LevelMode.cs']
    sources += sorted((project/'Assets/Plugins/3rd/NaughtyAttributes/Scripts/Core').rglob('*.cs'))
    sources += [Path(__file__).with_name('level_solver_probe.cs').resolve()]
    libraries = [kernel/'Unity.Mathematics.dll',kernel/'Unity.Splines.dll']
    for pattern in ['MessagePack.*/lib/netstandard2.1/MessagePack.dll','MessagePack.Annotations.*/lib/netstandard2.0/MessagePack.Annotations.dll','System.Collections.Immutable.*/lib/netstandard2.0/System.Collections.Immutable.dll','System.Runtime.CompilerServices.Unsafe.*/lib/netstandard2.0/System.Runtime.CompilerServices.Unsafe.dll','Microsoft.NET.StringTools.*/lib/netstandard2.0/Microsoft.NET.StringTools.dll']:
        libraries.append(next((project/'Assets/Packages').glob(pattern)))
    engine = list((unity/'Managed/UnityEngine').glob('*.dll'))
    args = ['-nologo','-target:exe','-unsafe','-langversion:latest','-out:'+str(root/'LevelSolverProbe.dll')]
    args += ['-r:'+str(p) for p in sorted(runtime.glob('*.dll'))+engine+libraries] + list(map(str,sources))
    rsp = root/'solver.rsp'; rsp.write_text('\n'.join('"'+s+'"' for s in args))
    build = subprocess.run([str(dotnet),str(csc),'@'+str(rsp)],cwd=repo,text=True,capture_output=True)
    (root/'compile.log').write_text(build.stdout+build.stderr)
    if build.returncode:
        raise RuntimeError(build.stdout+build.stderr)
    for p in sources+config_sources+libraries:
        manifest['sources'].append({'path':str(p),'sha256':digest(p)})
    for p in engine+libraries:
        target = root/p.name
        if not target.exists(): target.symlink_to(p)
    (root/'LevelSolverProbe.runtimeconfig.json').write_text(json.dumps({'runtimeOptions':{'tfm':'net6.0','framework':{'name':'Microsoft.NETCore.App','version':runtime.name}}}))
    # Bare Roslyn executables need an explicit dependency graph so the shipped
    # Immutable 8 assembly is selected instead of the shared framework's v6.
    deps = {'runtimeTarget':{'name':'.NETCoreApp,Version=v6.0'},'compilationOptions':{},'targets':{'.NETCoreApp,Version=v6.0':{}},'libraries':{}}
    for p in libraries+engine:
        key = p.stem + '/1.0.0'
        deps['targets']['.NETCoreApp,Version=v6.0'][key] = {'runtime':{p.name:{'assemblyVersion':'8.0.0.0' if p.stem=='System.Collections.Immutable' else '6.0.0.0' if p.stem=='System.Runtime.CompilerServices.Unsafe' else '0.0.0.0'}}}
        deps['libraries'][key] = {'type':'reference','serviceable':False,'sha512':''}
    (root/'LevelSolverProbe.deps.json').write_text(json.dumps(deps))
    opt.output.resolve().parent.mkdir(parents=True,exist_ok=True)
    result = subprocess.run([str(dotnet),str(root/'LevelSolverProbe.dll'),str(effective),str(opt.output.resolve()),str(opt.time_ms),str(opt.max_nodes),str(opt.max_frames),str(opt.aux_time_ms),str(opt.aux_attempt_time_ms)],cwd=repo,text=True,capture_output=True)
    (root/'run.log').write_text(result.stdout+result.stderr); print(result.stdout+result.stderr,flush=True)
    manifest['exit_code']=result.returncode
    manifest['head_after']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    manifest['sources_changed']=[s['path'] for s in manifest['sources'] if digest(Path(s['path']))!=s['sha256']]
    manifest['sources_changed'] += [s['source'] for s in manifest['adaptations'] if digest(Path(s['source'])) != s['sha256']]
    if opt.output.exists(): manifest['output_sha256']=digest(opt.output)
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    if result.returncode or manifest['sources_changed']:
        raise RuntimeError('Solver failed or source changed; inspect manifest and run.log')
if __name__ == '__main__': main()
