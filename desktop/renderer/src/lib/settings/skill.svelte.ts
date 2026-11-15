/**
 * 设置页「AI 与技能 → Agent 技能」的状态与动作。
 *
 * 技能是「把随包 skill 装到 ~/.agents/skills/」，与 AI 接口无关（一个走 API、
 * 一个由外部 agent 读文件），所以状态与动作单独一份，不和 aiConfig 混。
 */
import { toast } from '../store.svelte';

export interface SkillInfo {
  targetDir: string;
  installed: boolean;
  upToDate: boolean;
  fileCount: number;
  installedAt: number;
  error?: string;
}

export const skillState = $state({
  info: null as SkillInfo | null,
  busy: false,
  loaded: false,
});

export async function loadSkill() {
  try {
    const res = await window.kikusub?.skill?.status?.();
    skillState.info = res ? (res as SkillInfo) : null;
  } catch {
    skillState.info = null;
  } finally {
    skillState.loaded = true;
  }
}

export async function installSkill(paths: { output_dir: string; export_dir: string }) {
  if (skillState.busy) return;
  skillState.busy = true;
  try {
    const res = await window.kikusub.skill.install(paths);
    if (!res?.ok) {
      toast(res?.error || '技能配置失败', 'error');
      return;
    }
    // 安装接口不回 installedAt：重新拉一次 status 才是完整状态
    await loadSkill();
    toast(`已配置到 ${res.targetDir}`);
  } catch (err) {
    toast((err as Error).message, 'error');
  } finally {
    skillState.busy = false;
  }
}

export type SkillStatusLabel = '已配置' | '需更新' | '未配置';

export function skillStatusLabel(info: SkillInfo | null): SkillStatusLabel {
  if (!info?.installed) return '未配置';
  return info.upToDate ? '已配置' : '需更新';
}

export function skillStatusOk(info: SkillInfo | null): boolean {
  return Boolean(info?.installed && info?.upToDate);
}
