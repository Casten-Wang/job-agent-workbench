/*
 * 信号 · 动效与组件增强层（纯原生，零依赖）
 *
 * 仅做加法，不修改 app.js 的 renderAll / bindEvents / showView 既有语义：
 *  - 导航高亮滑块：在 .nav 内追加一个绝对定位药丸，跟随 .is-active 项滑动；
 *  - 轻提示 toast：暴露 window.uiToast(message, kind)，粉底 + 自动消失；
 *  - 入场错峰、悬停抬升、按压回弹由 ui-signals.css 负责（不在此处）。
 *
 * 主色沿用工作台粉色 --offer-pink，不使用原型荧光绿。
 */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  /* ---------- 导航高亮滑块 ---------- */

  function initNavHighlight() {
    var navs = Array.from(document.querySelectorAll(".nav"));
    if (!navs.length) return;

    navs.forEach(function (nav) {
      if (nav.querySelector(".nav__hl")) return;
      var hl = document.createElement("span");
      hl.className = "nav__hl";
      hl.setAttribute("aria-hidden", "true");
      nav.insertBefore(hl, nav.firstChild);

      function move() {
        var active = nav.querySelector(".nav-item.is-active");
        if (!active) {
          hl.classList.remove("is-on");
          return;
        }
        hl.style.transform = "translateY(" + active.offsetTop + "px)";
        hl.classList.add("is-on");
      }

      // 跟随既有点击：app.js 的 showView 会切换 .is-active，这里下一帧读最新状态
      nav.addEventListener("click", function (e) {
        if (e.target.closest(".nav-item")) {
          requestAnimationFrame(move);
        }
      });

      window.addEventListener("resize", move);
      move();
    });
  }

  /* ---------- 轻提示 toast ---------- */

  function ensureToastWrap() {
    var wrap = document.querySelector(".ui-toast-wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "ui-toast-wrap";
      wrap.setAttribute("role", "status");
      wrap.setAttribute("aria-live", "polite");
      document.body.appendChild(wrap);
    }
    return wrap;
  }

  function uiToast(message, kind) {
    if (!message) return;
    var wrap = ensureToastWrap();
    var toast = document.createElement("div");
    toast.className = "ui-toast";
    toast.setAttribute("data-kind", kind || "info");
    toast.textContent = String(message);
    wrap.appendChild(toast);

    requestAnimationFrame(function () {
      toast.classList.add("is-on");
    });

    var lifetime = 2400;
    setTimeout(function () {
      toast.classList.remove("is-on");
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 600);
    }, lifetime);

    return toast;
  }

  window.uiToast = uiToast;

  /* ---------- 启动 ---------- */

  ready(function () {
    initNavHighlight();
  });
})();
