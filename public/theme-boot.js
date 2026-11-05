// 페이지가 그려지기 전에 저장된 테마를 적용해 깜빡임을 막습니다 (module이 아닌 동기 스크립트).
(function () { try { var t = localStorage.getItem('qa_theme'); if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t); } catch (e) {} })();
