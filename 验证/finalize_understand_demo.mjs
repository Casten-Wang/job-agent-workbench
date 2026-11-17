// Publish this scoped UA demonstration after official schema validation.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = process.cwd();
const tool = path.join(root, '验证/understand-anything-tools/source/understand-anything-plugin');
const project = path.join(root, 'outputs/understand-anything/itsdangerous-672971d66a2e/project');
const ua = path.join(project, '.ua');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const write = (file, value) => {
  fs.writeFileSync(`${file}.tmp`, JSON.stringify(value, null, 2) + '\n');
  fs.renameSync(`${file}.tmp`, file);
};
const scope = read(path.join(project, '../scope.json'));
const assembled = read(path.join(ua, 'intermediate/assembled-graph.json'));
const graph = {
  version: '1.0.0',
  project: { name: 'ItsDangerous', languages: ['python', 'markdown', 'toml'], frameworks: [],
    description: 'Python带签名令牌库；本轮仅分析运行时代码、README和依赖配置。',
    analyzedAt: new Date().toISOString(), gitCommitHash: scope.commit_sha },
  nodes: assembled.nodes, edges: assembled.edges,
  layers: read(path.join(ua, 'intermediate/layers.json')),
  tour: read(path.join(ua, 'intermediate/tour.normalized.json')),
};
const core = await import(pathToFileURL(path.join(tool, 'packages/core/dist/index.js')).href);
const validation = core.validateGraph(graph);
write(path.join(project, '../schema-validation.json'), {
  tool_commit: 'b861852dda79273bd9d2e01c3160d42e2df510d2', success: validation.success,
  issues: validation.issues, fatal: validation.fatal ?? null,
  semantic_accuracy_assessed: false,
});
if (!validation.success || validation.issues.length) throw new Error('Official graph schema has unresolved issues');

const rawLessons = read(path.join(ua, 'intermediate/code-lessons.json'));
const files = {};
const fileTypes = new Set(['file', 'config', 'document', 'service', 'pipeline', 'table', 'schema', 'resource', 'endpoint']);
for (const node of graph.nodes.filter(node => fileTypes.has(node.type))) {
  const lesson = rawLessons.files?.[node.filePath];
  if (!lesson || !lesson.overview || !Array.isArray(lesson.sections)) throw new Error('Missing detailed lesson');
  if (lesson.sections.length > 10) throw new Error('Too many lesson sections');
  let previous = 0;
  for (const section of lesson.sections) {
    const range = section.lineRange;
    if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isInteger)
        || range[0] <= previous || range[1] < range[0]) throw new Error('Invalid or overlapping lesson sections');
    previous = range[1];
  }
  files[node.filePath] = lesson;
}
const lessons = {version: 1, generatedAt: new Date().toISOString(), files};
write(path.join(ua, 'intermediate/code-lessons.normalized.json'), lessons);
const scan = read(path.join(ua, 'intermediate/scan-result.json'));
const fingerprintInput = path.join(ua, 'intermediate/fingerprint-input.json');
write(fingerprintInput, {projectRoot: project, filePaths: scan.files.map(file => file.path), gitCommitHash: scope.commit_sha});
const fingerprint = spawnSync(process.execPath, [path.join(tool, 'skills/understand/build-fingerprints.mjs'), fingerprintInput], {
  cwd: root, encoding: 'utf8', windowsHide: true,
});
write(path.join(project, '../fingerprint-command.json'), {
  exit_code: fingerprint.status, stdout: fingerprint.stdout, stderr: fingerprint.stderr,
});
if (fingerprint.status !== 0 || !fingerprint.stdout.includes('Fingerprints baseline:')) throw new Error('Fingerprint baseline failed; metadata not advanced');
write(path.join(ua, 'knowledge-graph.json'), validation.data);
write(path.join(ua, 'code-lessons.json'), lessons);
write(path.join(ua, 'meta.json'), {lastAnalyzedAt: new Date().toISOString(), gitCommitHash: scope.commit_sha,
  version: '1.0.0', analyzedFiles: scan.files.length});
write(path.join(project, '../generation-provenance.json'), {
  upstream: 'Egonex-AI/Understand-Anything', upstream_commit: 'b861852dda79273bd9d2e01c3160d42e2df510d2',
  source_repository: scope.repository, source_commit: scope.commit_sha, analyzed_files: scope.selected_files,
  orchestration: 'Official Understand workflow, executed by this conversation with its file-analyzer, architecture, tour and lesson roles',
  official_scripts_run: ['scan-project.mjs', 'extract-import-map.mjs', 'compute-batches.mjs', 'extract-structure.mjs', 'merge-batch-graphs.py', 'normalize-tour.mjs', 'build-fingerprints.mjs'],
  semantic_generation: 'Current conversation LLM after source reading; not an unattended API service',
  model_tokens: null, model_tokens_note: 'Not metered in this probe; does not mean zero model cost',
  runtime_code_executed: false, user_authorship_confirmed: false, ability_assessed: false,
  adaptations: ['Input is a commit-pinned source copy; source manifest supplies gitCommitHash.',
    'Existing public sample authorization and explicitly stated scope used; no additional ignore confirmation.',
    'Intermediate and scratch files retained for review; no commit hooks installed.'],
});
console.log(JSON.stringify({nodes: graph.nodes.length, edges: graph.edges.length, layers: graph.layers.length,
  tour_steps: graph.tour.length, lesson_files: Object.keys(files).length,
  lesson_sections: Object.values(files).reduce((count, file) => count + file.sections.length, 0)}, null, 2));
