// Invoke the pinned upstream deterministic helpers. No analyzed Python is run.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const workspace = resolve(here, '../..');
const upstream = join(here, 'source');
const helpers = join(upstream, 'understand-anything-plugin/skills/understand');
const projectRoot = resolve(process.argv[2] ?? join(workspace, 'outputs/understand-anything/itsdangerous-672971d66a2e/project'));
const intermediate = join(projectRoot, '.ua/intermediate');
mkdirSync(intermediate, { recursive: true });
const read = path => JSON.parse(readFileSync(path, 'utf8'));
const write = (path, value) => writeFileSync(path, JSON.stringify(value, null, 2) + '\n');
const commands = [];
function run(script, args) {
  const result = spawnSync(process.execPath, [join(helpers, script), ...args], {
    encoding: 'utf8', cwd: projectRoot, windowsHide: true,
  });
  commands.push({ script, args, exit_code: result.status, stdout: result.stdout, stderr: result.stderr });
  if (result.stdout) process.stderr.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) {
    write(join(here, 'core-probe-commands.json'), commands);
    throw new Error(`Upstream helper failed: ${script}`);
  }
}

// Importing the real built core is part of the probe; no target project module is imported.
const core = await import(pathToFileURL(join(upstream, 'understand-anything-plugin/packages/core/dist/index.js')).href);
const scanPath = join(intermediate, 'scan-deterministic.json');
run('scan-project.mjs', [projectRoot, scanPath, '--exclude-analysis-data']);
const scan = read(scanPath);
const importInput = join(intermediate, 'import-input.json');
const importOutput = join(intermediate, 'import-map.json');
write(importInput, { projectRoot, files: scan.files });
run('extract-import-map.mjs', [importInput, importOutput]);
const imports = read(importOutput);
write(join(intermediate, 'scan-result.json'), { ...scan, importMap: imports.importMap });
run('compute-batches.mjs', [projectRoot]);
const batches = read(join(intermediate, 'batches.json'));
const structures = [];
for (const batch of batches.batches) {
  const input = join(intermediate, `structure-input-batch-${batch.batchIndex}.json`);
  const output = join(intermediate, `structure-batch-${batch.batchIndex}.json`);
  write(input, { projectRoot, batchFiles: batch.files, batchImportData: batch.batchImportData });
  run('extract-structure.mjs', [input, output]);
  const structure = read(output);
  structures.push({ batchIndex: batch.batchIndex, input, output,
    files: batch.files.map(f => f.path), filesAnalyzed: structure.filesAnalyzed,
    filesSkipped: structure.filesSkipped, filesUnreadable: structure.filesUnreadable,
    analysisOutcomes: structure.analysisOutcomes });
}
const snapshot = read(join(here, 'source-snapshot.json'));
const result = {
  upstream_repository: snapshot.repository, upstream_commit: snapshot.commit_sha,
  node_version: process.version, core_imported: true,
  available_core_entrypoints: ['validateGraph', 'sanitizeGraph', 'GraphBuilder', 'TreeSitterPlugin', 'buildFileAnalysisPrompt', 'buildTourGenerationPrompt'].filter(k => typeof core[k] === 'function'),
  projectRoot, scan_files: scan.totalFiles, scan_stats: scan.stats, scan_failures: scan.failures,
  import_stats: imports.stats, batch_count: batches.totalBatches,
  batches: structures, semantic_analysis_performed: false,
  note: 'Official deterministic scripts only. Semantic descriptions and graph assembly are supplied separately by the current session following upstream agent prompts.',
};
write(join(here, 'core-probe-commands.json'), commands);
write(join(here, 'core-probe-result.json'), result);
console.log(JSON.stringify(result, null, 2));
