import { parseArgs } from 'node:util';
import { createInterface } from 'node:readline/promises';
import { stdin, stdout } from 'node:process';
import { createDecisionAgent, runtimeFromEnv } from './agent.mjs';
import { HubClient, startLocalHub } from './hub-client.mjs';
import { Interview } from './interview.mjs';

const { values } = parseArgs({ options: { material: { type: 'string' }, session: { type: 'string' },
  role: { type: 'string', default: '初级后端开发' }, company: { type: 'string' }, round: { type: 'string', default: '前置核验' },
  check: { type: 'boolean' }, help: { type: 'boolean' } } });

function show(view) {
  if (view.message) console.log(`\n${view.message}`);
  if (view.recap) {
    console.log(JSON.stringify({ 待复核: view.recap.needs_review, 未评估: view.recap.not_assessed,
      补强任务: view.recap.improvement_tasks, 简历建议: view.recap.resume_suggestions }, null, 2));
  } else if (view.question && view.status === 'active') {
    console.log(`\n[${view.answered + 1}/${view.total}] ${view.question.text}\n考察：${view.question.intent}；${view.question.reason}`);
  } else console.log(`\n状态：${view.status}`);
}

if (values.help) {
  console.log('npm start -- --material <id> [--role 岗位] [--company 公司]\nnpm start -- --session <id>   恢复本轮\nnpm start -- --check          只检查模型访问配置\n命令：/hint /open-book /ai-assisted /skip /pause /resume /finish /retry /contribution 说明 /version 说明');
} else {
  let local;
  let rl;
  const interrupt = () => rl?.close();
  try {
    const runtime = await runtimeFromEnv();
    const agent = createDecisionAgent(runtime);
    if (values.check) console.log(JSON.stringify({ configured: true, ...agent.generation, live_model_called: false }));
    else {
      const client = process.env.INTERVIEW_HUB_URL
        ? new HubClient(process.env.INTERVIEW_HUB_URL, process.env.INTERVIEW_HUB_TOKEN)
        : (local = await startLocalHub()).client;
      const materials = (await client.request('/v1/materials')).items;
      const materialId = values.material || materials[0]?.material_id;
      if (!values.session && !materialId) throw new Error('还没有可用资料，请先运行 python -m interview_hub import-demo。');
      const interview = new Interview(client, agent);
      const target = { role: values.role, round: values.round, ...(values.company ? { company: values.company } : {}) };
      let view = await interview.start({ materialId, sessionId: values.session, target, resume: Boolean(values.session) });
      console.log(`会话 ${view.session_id}；模型 ${agent.generation.provider}/${agent.generation.model}。`);
      if (view.is_demo) console.log('当前使用公开项目样例，不是你的个人经历；不生成整体能力结论。');
      console.log('请独立作答；查阅源码或使用 AI 后用 /open-book 或 /ai-assisted 声明。控制命令：/hint /skip /pause /resume /finish /retry /contribution 说明 /version 说明。Ctrl+C 退出，已记录的进度保留。');
      show(view);
      rl = createInterface({ input: stdin, output: stdout });
      process.once('SIGINT', interrupt);
      if (view.status === 'completed') rl.close();
      for await (const input of rl) {
        const text = input.trim();
        if (!text) continue;
        const match = text.match(/^\/(hint|open-book|ai-assisted|skip|pause|resume|finish|retry|contribution|version)(?:\s+([\s\S]+))?$/);
        const commands = { hint: 'request_hint', 'open-book': 'open_book', 'ai-assisted': 'ai_assisted', contribution: 'correct_contribution', version: 'correct_version' };
        try {
          if (['contribution', 'version'].includes(match?.[1]) && !match[2]) { console.log('请在命令后补充修正说明。'); continue; }
          view = await interview.handle(text, match ? commands[match[1]] || match[1] : undefined);
          show(view);
          if (view.status === 'completed') break;
        } catch (error) { console.error(error.message.startsWith('Pi ') ? error.message : '本轮操作未完成，进度已保留。可 /retry 或重新启动恢复。'); }
      }
    }
  } catch (error) {
    console.error(error.status ? `服务请求失败（${error.status}）。` : error.message);
    process.exitCode = 1;
  } finally { process.removeListener('SIGINT', interrupt); rl?.close(); await local?.close(); }
}
