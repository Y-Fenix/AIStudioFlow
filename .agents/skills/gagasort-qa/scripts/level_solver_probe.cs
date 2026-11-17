using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Threading;
using GagaSort;
using MessagePack;

internal static class LevelSolverProbe {
    private static GagaSortLogicConfig Config(JsonElement input) {
        var ctor = typeof(GagaSortLogicConfig).GetConstructors().OrderByDescending(c => c.GetParameters().Length).First();
        var values = ctor.GetParameters().Select(p => {
            if (!input.TryGetProperty(p.Name, out var v)) throw new Exception("Missing logic_config parameter: " + p.Name);
            return p.ParameterType == typeof(HashSet<EGagaSortDuckColor>)
                ? (object)new HashSet<EGagaSortDuckColor>(v.EnumerateArray().Select(x => (EGagaSortDuckColor)x.GetInt32()))
                : (object)v.GetSingle();
        }).ToArray();
        return (GagaSortLogicConfig)ctor.Invoke(values);
    }

    // Fresh production factory/runtime, no search snapshots restored: prove the
    // recorded command sequence itself reaches the authoritative completion bit.
    private static object Replay(GagaSortLevelData level, GagaSortLogicConfig config, List<int[]> actions, int endFrame) {
        var model = new GagaSortLevelModelFactory().Create(level.LevelMode, level.LevelId, level, config, true, true, null);
        model.State = EGagaSortLevelState.Playing;
        model.IsInputBlocked = false;
        var runtime = new GagaSortLogicRuntime(); runtime.Build(model, config);
        int cursor = 0;
        try {
        while (runtime.CurrentFrameId < endFrame) {
            if (cursor < actions.Count && actions[cursor][0] == runtime.CurrentFrameId) {
                int slot = actions[cursor++][1];
                if (!model.CanClickSlot(slot)) throw new Exception("Replay command not clickable at frame " + runtime.CurrentFrameId);
                runtime.EnqueueCommand(new GagaSortClickSlotCommand(slot, runtime.CurrentFrameId));
            }
            runtime.Tick(GagaSortSolvabilityOptions.FixedDeltaTimeSeconds);
        }
        if (!model.HasCompleted || model.HasFailed || cursor != actions.Count) throw new Exception("Successful path failed fresh production Runtime replay");
        return new { has_completed=model.HasCompleted, has_failed=model.HasFailed, frame=runtime.CurrentFrameId, commands=cursor, independent_runtime=true };
        } finally { runtime.Release(); }
    }
    private static object Auxiliary(GagaSortLevelData level, GagaSortLogicConfig config,
        int totalBudgetMs, int attemptBudgetMs, out List<int[]> actions, out int endFrame, out object replay) {
        actions = null; endFrame = 0; replay = null;
        var attempts = new List<object>();
        var clock = Stopwatch.StartNew();
        if (totalBudgetMs > 0) {
            try {
                var evaluator = new GagaSortDifficultyEvaluator();
                var prepared = evaluator.Prepare(level, config, level.Belt.MaxCount);
                if (!prepared.IsValid) throw new Exception(prepared.Error);
                foreach (var profile in new[] { EGagaSortDifficultyPlayerProfile.Novice, EGagaSortDifficultyPlayerProfile.Typical }) {
                    int remaining = totalBudgetMs - (int)clock.ElapsedMilliseconds;
                    if (remaining <= 0) break;
                    int allowance = Math.Min(attemptBudgetMs, remaining);
                    const int seed = 20261028;
                    var watch = Stopwatch.StartNew();
                    using var cancel = new CancellationTokenSource(allowance);
                    try {
                        var result = evaluator.Evaluate(prepared, new GagaSortDifficultyEvaluationOptions(
                            level.Belt.MaxCount, profile, attemptCount:1, randomSeed:seed,
                            maxSimulationFrames:18000, maxDecisionCount:600,
                            extraSlotMode:EGagaSortDifficultyExtraSlotMode.Locked, maxDegreeOfParallelism:1), cancel.Token);
                        string status = !string.IsNullOrEmpty(result.Error) ? "ProbeError"
                            : result.PassedCount > 0 ? "Passed" : result.DeadlockedCount > 0 ? "AttemptDeadlocked" : "BudgetExceeded";
                        object candidateReplay = null;
                        string error = result.Error;
                        if (result.PassedCount > 0) {
                            try {
                                candidateReplay = Replay(level, config, evaluator.TraceActions, evaluator.TraceEndFrame);
                            } catch (Exception e) { status = "ReplayMismatch"; error = e.ToString(); }
                        }
                        attempts.Add(new { profile=profile.ToString(), seed, budget_ms=allowance,
                            status, elapsed_ms=watch.ElapsedMilliseconds, decisions=result.AverageDecisionCount,
                            simulated_frames=result.P90SimulationFrames, action_count=evaluator.TraceActions.Count,
                            completion_frame=evaluator.TraceEndFrame, replay=candidateReplay, reason=error });
                        if (candidateReplay != null) {
                            actions = new(evaluator.TraceActions); endFrame = evaluator.TraceEndFrame;
                            replay = candidateReplay; break;
                        }
                    } catch (OperationCanceledException) {
                        attempts.Add(new { profile=profile.ToString(), seed, budget_ms=allowance,
                            status="CancelledBudget", elapsed_ms=watch.ElapsedMilliseconds,
                            action_count=evaluator.TraceActions.Count });
                    }
                }
            } catch (Exception e) { attempts.Add(new { status="ProbeError", reason=e.ToString() }); }
        }
        return new { method="production DifficultyEvaluator; original capacity; locked Extra; no boosters",
            total_budget_ms=totalBudgetMs, per_attempt_budget_ms=attemptBudgetMs,
            max_frames=18000, max_decisions=600,
            budget_enforcement="cooperative cancellation at production checkpoints; includes preparation; fresh replay may finish after budget",
            elapsed_ms=clock.ElapsedMilliseconds, attempts };
    }
    public static int Main(string[] args) {
        var results = new List<object>();
        using var doc = JsonDocument.Parse(File.ReadAllText(args[0]));
        var config = Config(doc.RootElement.GetProperty("logic_config"));
        if (!config.IsValid(out var configError)) throw new Exception(configError);
        foreach (var entry in doc.RootElement.GetProperty("levels").EnumerateArray()) {
            string id = entry.GetProperty("level_id").GetString();
            var levelClock = Stopwatch.StartNew();
            try {
                byte[] raw = MessagePackSerializer.ConvertFromJson(entry.GetProperty("raw_record").GetRawText());
                var level = MessagePackSerializer.Deserialize<GagaSortLevelData>(raw, MessagePackSerializerOptions.Standard);
                var validationResult = new GagaSortLevelValidator().ValidateLevelRecord(level,config);
                var validation = new { valid=validationResult.IsValid, issues=validationResult.Issues.Select(i => new {severity=i.Severity.ToString(),field=i.FieldPath,message=i.Message}) };
                var solver = new GagaSortSolvabilitySolver();
                var options = new GagaSortSolvabilityOptions(maxElapsedMilliseconds:int.Parse(args[2]),maxExpandedNodes:int.Parse(args[3]),maxSimulationFrames:int.Parse(args[4]));
                var result = solver.Solve(level,config,options);
                object replay = result.Status == EGagaSortSolvabilityStatus.Solvable ? Replay(level,config,solver.TraceActions,solver.TraceEndFrame) : null;
                string status = result.Status.ToString();
                string proof = replay != null ? "production_solver_fresh_replay" : null;
                var actions = solver.TraceActions; int endFrame = solver.TraceEndFrame;
                object auxiliary = null;
                if (result.Status == EGagaSortSolvabilityStatus.Inconclusive) {
                    auxiliary = Auxiliary(level,config,int.Parse(args[5]),int.Parse(args[6]),out var auxActions,out var auxEndFrame,out var auxReplay);
                    if (auxReplay != null) { status="Solvable"; proof="production_evaluator_fresh_replay"; actions=auxActions; endFrame=auxEndFrame; replay=auxReplay; }
                }
                var search = new { status=result.Status.ToString(), expanded_nodes=result.ExpandedNodeCount,
                    simulated_frames=result.SimulatedFrameCount, elapsed_ms=result.ElapsedMilliseconds, reason=result.FailureReason };
                results.Add(new { level_id=id, validation, status, proof_method=proof, expanded_nodes=result.ExpandedNodeCount, simulated_frames=result.SimulatedFrameCount, elapsed_ms=result.ElapsedMilliseconds, total_elapsed_ms=levelClock.ElapsedMilliseconds, reason=status=="Solvable" ? "" : result.FailureReason, search_result=search, auxiliary, actions=actions.Select(a => new {frame=a[0],slot_id=a[1]}), completion_frame=endFrame, replay });
                Console.WriteLine(id + " " + status + " search=" + result.ElapsedMilliseconds + "ms " + proof);
            } catch (Exception e) {
                results.Add(new { level_id=id,status="ProbeError",reason=e.ToString() });
                Console.WriteLine(id + " ProbeError " + e.Message);
            }
            File.WriteAllText(args[1],JsonSerializer.Serialize(new { schema_version=1,budget=new {time_ms=int.Parse(args[2]),max_nodes=int.Parse(args[3]),max_frames=int.Parse(args[4]),aux_time_ms=int.Parse(args[5]),aux_attempt_time_ms=int.Parse(args[6])},scope="production solver + production evaluator fallback, full records, fixed 60Hz, locked Extra, no boosters",levels=results },new JsonSerializerOptions{WriteIndented=true}));
        }
        return 0;
    }
}
