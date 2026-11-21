/**
 * 宿主 UI 组件包：外部插件通过 ``window.__AMRITA_HOST__.UI`` 取用这里的组件。
 *
 * 目的只有一个：让插件的观感跟宿主一致。插件用这些组件时，产出的
 * className 全部来自宿主自己的源码，因此一定在宿主的 Tailwind 产物里；
 * 插件自己写 ``bg-fuchsia-700`` 这种宿主没用过的类则会静默失效。
 *
 * 这个模块由 :func:`loadRemoteComponent` 在首次加载插件前动态 import，
 * 不进入首屏 bundle；插件页是懒加载的，晚一点拿到 UI 不会有额外代价。
 *
 * 增删导出等于改变宿主与插件的契约，需同步 bump
 * ``remote.tsx`` 的 ``HOST_CONTRACT_VERSION``，并更新
 * ``@amrita-constant/webui-plugin-kit`` 的 ``ui-exports.ts``。
 */

export * from "@amrita-constant/ambot-ui";
