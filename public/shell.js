// 공통 셸: 테마(light/dark/system) 적용과 사이드바 활성 표시. 모든 페이지가 먼저 불러옵니다.
const THEME_KEY = 'qa_theme';
export function applyTheme(value) {
  const theme = ['light', 'dark', 'system'].includes(value) ? value : 'system';
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
  for (const button of document.querySelectorAll('.theme-switch button')) button.classList.toggle('active', button.dataset.theme === theme);
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* storage may be unavailable */ }
  return theme;
}
export function currentTheme() { try { return localStorage.getItem(THEME_KEY) || 'system'; } catch { return 'system'; } }
export function mountShell() {
  applyTheme(currentTheme());
  for (const button of document.querySelectorAll('.theme-switch button')) button.addEventListener('click', () => applyTheme(button.dataset.theme));
  const page = document.body.dataset.page;
  for (const link of document.querySelectorAll('.sidebar nav a')) link.classList.toggle('active', link.dataset.page === page);
}
mountShell();
