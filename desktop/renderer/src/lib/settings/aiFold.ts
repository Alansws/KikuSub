/**
 * 设置 → AI 与技能 →「进阶：单句判定独立模型与本地部署」的纯逻辑（2026-11-21，Step 6）。
 *
 * 折成纯函数（不带 runes）是为了能被 `node --test` 直接覆盖：
 * 默认开合是「既有高级配置不会因为折叠而消失」的唯一保证，靠手点很容易回归。
 */

/** 判断只看这几个字段，结构化类型让 `AiConfig` 直接传进来。 */
export type AiFoldConfig = {
  auto_arbitrate: boolean;
  arbitrate_base_url: string;
  arbitrate_model: string;
  arbitrate_loopback: boolean;
};

/** 已单独配过单句判定（地址 / 模型 / Key）或开了自动判定 → 折叠区默认展开。 */
export function advancedAiInUse(cfg: AiFoldConfig | null, arbHasKey: boolean): boolean {
  if (!cfg) return false;
  if (cfg.auto_arbitrate) return true;
  if (cfg.arbitrate_base_url.trim() || cfg.arbitrate_model.trim()) return true;
  return arbHasKey;
}

/** 收起时的摘要：跟随全局还是独立模型、自动判定开没开，不展开也看得见。 */
export function advancedAiMeta(cfg: AiFoldConfig | null, arbHasKey: boolean): string {
  if (!cfg) return '';
  const scope = cfg.arbitrate_loopback
    ? '本机 LM Studio'
    : cfg.arbitrate_base_url.trim() || cfg.arbitrate_model.trim() || arbHasKey
      ? '已单独配置'
      : '跟随全局';
  return `${scope} · 自动判定${cfg.auto_arbitrate ? '开' : '关'}`;
}
