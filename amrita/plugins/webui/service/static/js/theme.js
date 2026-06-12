/**
 * Amrita WebUI - 共享主题管理
 *
 * 从 base.html 提取，供所有页面统一使用。
 * Tailwind 使用 .dark class 控制暗色模式。
 *
 * 用法:
 *   <script src="/static/js/theme.js"></script>
 *   <!-- HTML: -->
 *   <button onclick="toggleTheme()" id="themeToggle">...</button>
 *
 * 全局函数:
 *   setTheme("dark"|"light")
 *   toggleTheme()
 *   detectSystemTheme() → "dark"|"light"
 *   initTheme()
 */

(function () {
  "use strict";

  window.setTheme = function (theme) {
    var html = document.documentElement;
    var toggle = document.getElementById("themeToggle");
    var ghBtn = document.getElementById("githubButton");
    if (theme === "dark") {
      html.classList.add("dark");
      if (toggle) toggle.innerHTML = '<i class="fas fa-sun"></i>';
      if (ghBtn)
        ghBtn.innerHTML =
          '<img src="/static/images/github-mark-white.svg" alt="GitHub" width="25" height="25">';
      try {
        localStorage.setItem("theme", "dark");
      } catch (e) {
        /* ignore */
      }
    } else {
      html.classList.remove("dark");
      if (toggle) toggle.innerHTML = '<i class="fas fa-moon"></i>';
      if (ghBtn)
        ghBtn.innerHTML =
          '<img src="/static/images/github-mark.svg" alt="GitHub" width="25" height="25">';
      try {
        localStorage.setItem("theme", "light");
      } catch (e) {
        /* ignore */
      }
    }
  };

  window.toggleTheme = function () {
    setTheme(
      document.documentElement.classList.contains("dark") ? "light" : "dark"
    );
  };

  window.detectSystemTheme = function () {
    return window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  };

  window.initTheme = function () {
    var saved;
    try {
      saved = localStorage.getItem("theme");
    } catch (e) {
      saved = null;
    }
    setTheme(saved || detectSystemTheme());

    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", function (e) {
        try {
          if (!localStorage.getItem("theme"))
            setTheme(e.matches ? "dark" : "light");
        } catch (err) {
          /* ignore */
        }
      });
  };
})();
