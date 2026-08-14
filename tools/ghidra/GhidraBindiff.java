// GhidraBindiff.java — binary diff via Ghidra Version Tracking (issue #308).
//
// Absorbed design from REA's DiffSessionManager (VTProgramCorrelatorFactory),
// re-implemented against this repo's GhidraJsonScript base (issue #293).
//
// analyzeHeadless imports BOTH samples into one project and runs this
// postScript once per imported program; the correlation runs only while
// processing the target program (the base DomainFile is in the project by
// then).  Two correlators run against one VT session:
//
//   - ExactMatchInstructionsProgramCorrelator     -> identical functions
//   - CombinedFunctionAndDataReferenceProgramCorrelator -> changed functions
//     (a modified body can still match via call/data references)
//
// Every kept pair carries the 恒检 lenses: body_bytes_changed (byte compare
// of both function bodies) + callees_added/callees_removed/callees_common.
// Output: bindiff.v1 JSON (schema/program/image_base meta + summary +
// per-function category entries) written to the --out path.
//
// Match selection (self-consistent counts, deterministic): all candidate
// matches from both correlators are sorted by similarity DESC (then source /
// destination entry addresses ASC) and selected greedily so each base
// function and each target function is used by AT MOST one kept pair.  Thus:
//   identical + changed == matched
//   matched + added   == total_target
//   matched + removed == total_base
//
// Ghidra 12.1.2 API usage (verified against the shipped jars: javap signature
// checks + a full-jar javac compile smoke test, see tests/test_bindiff.py):
//   DomainFile.getImmutableDomainObject(consumer, DomainFile.DEFAULT_VERSION,
//       monitor)                     — open the base program (no ProgramDB
//                                      constructor takes a DomainFile)
//   new VTSessionDB(String, Program, Program, Object consumer)
//                                      (static createVTSession is deprecated
//                                      for removal)
//   factory.createDefaultOptions() / factory.createCorrelator(Program,
//       AddressSetView, Program, AddressSetView, VTOptions)
//   correlator.correlate(VTSession, TaskMonitor) -> VTMatchSet (the returned
//       set carries this correlator's matches; VTSession has no single
//       getMatchSet())
//   match.getSourceAddress()/getDestinationAddress() -> Address (already an
//       Address — no .getAddress() unwrap)
//   session.release(consumer)       — VTSession has no dispose()
//
// All inputs are script args (--base/--target are the imported program NAMES
// — basenames, not paths; --out): no hardcoded sample paths or hashes.
// Pure Java — no Jython runtime annotation.
import ghidra.feature.vt.api.correlator.program.CombinedFunctionAndDataReferenceProgramCorrelatorFactory;
import ghidra.feature.vt.api.correlator.program.ExactMatchInstructionsProgramCorrelatorFactory;
import ghidra.feature.vt.api.db.VTSessionDB;
import ghidra.feature.vt.api.main.VTMatch;
import ghidra.feature.vt.api.main.VTMatchSet;
import ghidra.feature.vt.api.main.VTProgramCorrelator;
import ghidra.feature.vt.api.main.VTProgramCorrelatorFactory;
import ghidra.feature.vt.api.main.VTSession;
import ghidra.feature.vt.api.util.VTOptions;
import ghidra.framework.model.DomainFile;
import ghidra.framework.model.DomainFolder;
import ghidra.framework.model.Project;
import ghidra.framework.model.ProjectData;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Program;
import ghidra.program.model.mem.Memory;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class GhidraBindiff extends GhidraJsonScript {

    /** DomainObject consumer for the programs opened by this script. */
    private final Object consumer = new Object();

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String baseName = getArg(args, "base", "");
        String targetName = getArg(args, "target", "");
        String outPath = getArg(args, "out", "");
        if (baseName.isEmpty() || targetName.isEmpty() || outPath.isEmpty()) {
            throw new IllegalArgumentException(
                    "GhidraBindiff requires --base= and --target= and --out=");
        }
        // Headless runs this postScript once per imported program; correlate
        // only when processing the target program (base is already imported).
        if (!currentProgram.getName().equals(targetName)) {
            return;
        }
        try {
            Map<String, Object> artifact = correlateAndBuild(baseName, targetName);
            writeJson(outPath, artifact);
        }
        catch (Throwable t) {
            // Fail-closed: record the failure inside the artifact so the async
            // job protocol can report it, then rethrow (non-zero headless exit).
            try {
                Map<String, Object> failed = new LinkedHashMap<>();
                failed.putAll(meta("bindiff.v1", "GhidraBindiff"));
                failed.put("error", t.toString());
                writeJson(outPath, failed);
            }
            catch (Throwable ignored) {
                // artifact write itself failed — nothing more to do
            }
            if (t instanceof Exception) {
                throw (Exception) t;
            }
            throw new RuntimeException(t);
        }
    }

    private Map<String, Object> correlateAndBuild(String baseName, String targetName)
            throws Exception {
        Project project = state.getProject();
        if (project == null) {
            throw new IllegalStateException("no active project — headless run required");
        }
        ProjectData data = project.getProjectData();
        DomainFolder root = data.getRootFolder();
        DomainFile baseFile = root.getFile(baseName);
        if (baseFile == null) {
            throw new IllegalStateException(
                    "imported base program not found in project root: " + baseName);
        }

        Program baseProgram = null;
        VTSession session = null;
        try {
            baseProgram = (Program) baseFile.getImmutableDomainObject(consumer,
                    DomainFile.DEFAULT_VERSION, getMonitor());
            Program targetProgram = currentProgram; // already open — do not reopen

            session = new VTSessionDB("ghidra-bindiff", baseProgram,
                    targetProgram, consumer);

            List<String> correlatorNames = new ArrayList<>();
            List<VTMatch> candidates = new ArrayList<>();
            runCorrelator(new ExactMatchInstructionsProgramCorrelatorFactory(),
                    session, baseProgram, targetProgram, correlatorNames, candidates);
            runCorrelator(new CombinedFunctionAndDataReferenceProgramCorrelatorFactory(),
                    session, baseProgram, targetProgram, correlatorNames, candidates);

            DiffResult result = classify(candidates, baseProgram, targetProgram);
            return buildArtifact(baseName, targetName, correlatorNames, result);
        }
        finally {
            if (session != null) {
                session.release(consumer);
            }
            if (baseProgram != null) {
                baseProgram.release(consumer);
            }
        }
    }

    private void runCorrelator(VTProgramCorrelatorFactory factory, VTSession session,
            Program source, Program destination, List<String> correlatorNames,
            List<VTMatch> candidates) throws Exception {
        VTOptions options = factory.createDefaultOptions();
        VTProgramCorrelator correlator = factory.createCorrelator(source,
                source.getMemory(), destination, destination.getMemory(), options);
        VTMatchSet matchSet = correlator.correlate(session, getMonitor());
        candidates.addAll(matchSet.getMatches());
        correlatorNames.add(factory.getName());
    }

    /** One candidate pair resolved from a VTMatch (function-level). */
    private static final class Candidate {
        final Function baseFn;
        final Function targetFn;
        final double similarity;
        final double confidence;

        Candidate(Function baseFn, Function targetFn, VTMatch match) {
            this.baseFn = baseFn;
            this.targetFn = targetFn;
            this.similarity = match.getSimilarityScore().getScore();
            this.confidence = match.getConfidenceScore().getScore();
        }
    }

    /**
     * Deterministic greedy one-to-one selection: candidates sorted by
     * similarity DESC (then entry addresses ASC), each base/target function
     * used at most once.  Kept pairs become identical/changed; unused target
     * functions become added, unused base functions become removed — the
     * summary is therefore always self-consistent (matched + added ==
     * total_target, matched + removed == total_base).
     */
    private DiffResult classify(List<VTMatch> matches, Program baseProgram,
            Program targetProgram) throws Exception {
        List<Candidate> candidates = new ArrayList<>();
        for (VTMatch match : matches) {
            Address sourceAddr = match.getSourceAddress();
            Address destAddr = match.getDestinationAddress();
            if (sourceAddr == null || destAddr == null) {
                continue;
            }
            Function baseFn =
                    baseProgram.getFunctionManager().getFunctionContaining(sourceAddr);
            Function targetFn =
                    targetProgram.getFunctionManager().getFunctionContaining(destAddr);
            if (baseFn == null || targetFn == null) {
                continue;
            }
            candidates.add(new Candidate(baseFn, targetFn, match));
        }
        Collections.sort(candidates, new Comparator<Candidate>() {
            @Override
            public int compare(Candidate a, Candidate b) {
                int bySim = Double.compare(b.similarity, a.similarity);
                if (bySim != 0) {
                    return bySim;
                }
                int bySource = a.baseFn.getEntryPoint().compareTo(
                        b.baseFn.getEntryPoint());
                if (bySource != 0) {
                    return bySource;
                }
                return a.targetFn.getEntryPoint().compareTo(b.targetFn.getEntryPoint());
            }
        });

        Set<Address> usedBaseEntries = new HashSet<>();
        Set<Address> usedTargetEntries = new HashSet<>();
        List<Map<String, Object>> functions = new ArrayList<>();
        int identicalCount = 0;
        int changedCount = 0;
        for (Candidate candidate : candidates) {
            Address baseEntry = candidate.baseFn.getEntryPoint();
            Address targetEntry = candidate.targetFn.getEntryPoint();
            if (!usedBaseEntries.add(baseEntry)) {
                continue; // base function already paired with a stronger match
            }
            if (!usedTargetEntries.add(targetEntry)) {
                usedBaseEntries.remove(baseEntry); // roll back: target taken —
                continue;                          // this base stays unmatched
            }
            boolean identical = candidate.similarity >= 1.0;
            if (identical) {
                identicalCount++;
            }
            else {
                changedCount++;
            }

            Map<String, Object> lenses = new LinkedHashMap<>();
            lenses.put("body_bytes_changed", Boolean.valueOf(
                    bodyBytesChanged(baseProgram, candidate.baseFn,
                            targetProgram, candidate.targetFn)));
            CalleeDelta calleeDelta = calleeDelta(baseProgram, candidate.baseFn,
                    targetProgram, candidate.targetFn);
            lenses.put("callees_added", calleeDelta.added);
            lenses.put("callees_removed", calleeDelta.removed);
            lenses.put("callees_common", Integer.valueOf(calleeDelta.common));

            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("category", identical ? "identical" : "changed");
            entry.put("base", functionInfo(candidate.baseFn));
            entry.put("target", functionInfo(candidate.targetFn));
            entry.put("similarity", Double.valueOf(candidate.similarity));
            entry.put("confidence", Double.valueOf(candidate.confidence));
            entry.put("lenses", lenses);
            functions.add(entry);
        }

        int addedCount = 0;
        for (Function fn : allFunctions(targetProgram)) {
            if (!usedTargetEntries.contains(fn.getEntryPoint())) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("category", "added");
                entry.put("base", null);
                entry.put("target", functionInfo(fn));
                entry.put("similarity", null);
                entry.put("confidence", null);
                entry.put("lenses", null);
                functions.add(entry);
                addedCount++;
            }
        }
        int removedCount = 0;
        for (Function fn : allFunctions(baseProgram)) {
            if (!usedBaseEntries.contains(fn.getEntryPoint())) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("category", "removed");
                entry.put("base", functionInfo(fn));
                entry.put("target", null);
                entry.put("similarity", null);
                entry.put("confidence", null);
                entry.put("lenses", null);
                functions.add(entry);
                removedCount++;
            }
        }
        return new DiffResult(functions, identicalCount, changedCount, addedCount,
                removedCount, allFunctions(baseProgram).size(),
                allFunctions(targetProgram).size());
    }

    /** All functions of a program (deterministic entry-address order). */
    private List<Function> allFunctions(Program program) {
        List<Function> functions = new ArrayList<>();
        FunctionIterator it = program.getFunctionManager().getFunctions(true);
        while (it.hasNext()) {
            functions.add(it.next());
        }
        return functions;
    }

    /** 恒检 lens: byte-compare both function bodies (always computed). */
    private boolean bodyBytesChanged(Program baseProgram, Function baseFn,
            Program targetProgram, Function targetFn) {
        return !Arrays.equals(collectBodyBytes(baseProgram, baseFn),
                collectBodyBytes(targetProgram, targetFn));
    }

    private byte[] collectBodyBytes(Program program, Function function) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Memory memory = program.getMemory();
        for (ghidra.program.model.address.AddressRange range : function.getBody().getAddressRanges()) {
            Address address = range.getMinAddress();
            while (address != null && address.compareTo(range.getMaxAddress()) <= 0) {
                try {
                    out.write(memory.getByte(address) & 0xFF);
                }
                catch (Exception e) {
                    break; // unreadable byte — treat as end of readable body
                }
                try {
                    address = address.addNoWrap(1);
                }
                catch (ghidra.program.model.address.AddressOverflowException e) {
                    break; // end of the address space
                }
            }
        }
        return out.toByteArray();
    }

    /** Callee names (entry-address + name), sorted for stable comparison. */
    private List<String> calleeNames(Program program, Function function) {
        Set<Function> callees = function.getCalledFunctions(getMonitor());
        List<String> names = new ArrayList<>();
        for (Function callee : callees) {
            names.add(formatAddress(callee.getEntryPoint()) + " " + callee.getName());
        }
        Collections.sort(names);
        return names;
    }

    private static final class CalleeDelta {
        final List<String> added;
        final List<String> removed;
        final int common;

        CalleeDelta(List<String> added, List<String> removed, int common) {
            this.added = added;
            this.removed = removed;
            this.common = common;
        }
    }

    private CalleeDelta calleeDelta(Program baseProgram, Function baseFn,
            Program targetProgram, Function targetFn) {
        List<String> baseCallees = calleeNames(baseProgram, baseFn);
        List<String> targetCallees = calleeNames(targetProgram, targetFn);
        Set<String> baseSet = new HashSet<>(baseCallees);
        Set<String> targetSet = new HashSet<>(targetCallees);
        List<String> added = new ArrayList<>();
        for (String callee : targetCallees) {
            if (!baseSet.contains(callee)) {
                added.add(callee);
            }
        }
        List<String> removed = new ArrayList<>();
        for (String callee : baseCallees) {
            if (!targetSet.contains(callee)) {
                removed.add(callee);
            }
        }
        int common = 0;
        for (String callee : baseSet) {
            if (targetSet.contains(callee)) {
                common++;
            }
        }
        return new CalleeDelta(added, removed, common);
    }

    private Map<String, Object> functionInfo(Function function) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("address", formatAddress(function.getEntryPoint()));
        info.put("name", function.getName());
        info.put("size", Long.valueOf(function.getBody().getNumAddresses()));
        return info;
    }

    private Map<String, Object> buildArtifact(String baseName, String targetName,
            List<String> correlatorNames, DiffResult result) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("identical", Integer.valueOf(result.identical));
        summary.put("changed", Integer.valueOf(result.changed));
        summary.put("added", Integer.valueOf(result.added));
        summary.put("removed", Integer.valueOf(result.removed));
        summary.put("matched", Integer.valueOf(result.identical + result.changed));
        summary.put("total_base", Integer.valueOf(result.totalBase));
        summary.put("total_target", Integer.valueOf(result.totalTarget));

        Map<String, Object> root = new LinkedHashMap<>();
        root.putAll(meta("bindiff.v1", "GhidraBindiff"));
        root.put("base_program", baseName);
        root.put("correlators", correlatorNames);
        root.put("summary", summary);
        root.put("functions", result.functions);
        return root;
    }

    private static final class DiffResult {
        final List<Map<String, Object>> functions;
        final int identical;
        final int changed;
        final int added;
        final int removed;
        final int totalBase;
        final int totalTarget;

        DiffResult(List<Map<String, Object>> functions, int identical, int changed,
                int added, int removed, int totalBase, int totalTarget) {
            this.functions = functions;
            this.identical = identical;
            this.changed = changed;
            this.added = added;
            this.removed = removed;
            this.totalBase = totalBase;
            this.totalTarget = totalTarget;
        }
    }
}
