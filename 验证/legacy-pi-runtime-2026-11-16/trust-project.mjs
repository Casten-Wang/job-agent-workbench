import { fileURLToPath } from 'node:url';
import { ProjectTrustStore } from '@earendil-works/pi-coding-agent';
const root = fileURLToPath(new URL('../', import.meta.url));
const directory = fileURLToPath(new URL('../.pi/runtime/dev/', import.meta.url));
new ProjectTrustStore(directory).set(root, true);
console.log('已在本项目独立的 Pi 配置目录中信任当前项目；未修改全局信任配置。');
