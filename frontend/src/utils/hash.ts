/**
 * 简单哈希函数
 * 用于为新闻/报告生成唯一 ID（基于 title + source + ts）
 */

/**
 * 将字符串转换为简单的哈希值（16进制字符串）
 * 使用 DJB2 变体算法，快速且分布均匀
 */
export function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    // hash * 31 + charCode (使用位运算优化)
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0; // 转换为 32 位整数
  }
  return Math.abs(hash).toString(16);
}

/**
 * 为新闻条目生成唯一 ID
 * @param title 新闻标题
 * @param source 新闻来源
 * @param ts 时间戳
 */
export function generateNewsId(title: string, source?: string, ts?: string): string {
  const combined = `${title}${source || ''}${ts || ''}`;
  return simpleHash(combined);
}
