export function buildWorkbenchReportHref(reportId: string): string {
  return `/workbench?report=${encodeURIComponent(reportId.trim())}`;
}

export function buildReportFollowUpPrompt(title: string, reportId: string): string {
  const displayTitle = title.trim() || reportId.trim() || '未命名报告';
  return `基于报告《${displayTitle}》，`;
}

export function buildReportFollowUpHref(title: string, reportId: string): string {
  const params = new URLSearchParams({
    prompt: buildReportFollowUpPrompt(title, reportId),
  });
  return `/chat?${params.toString()}`;
}
