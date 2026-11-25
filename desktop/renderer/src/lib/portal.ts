/**
 * 把浮层挂到 `document.body` 下。
 *
 * 为什么不能留在组件内：`.view-enter.animated` 的切页动画带 `animation-fill-mode: both`，
 * 结束后计算出的 transform 仍是 identity matrix——它会让 `position: fixed` 相对这个
 * 容器定位，右键菜单会被整体推开「侧栏 + 工具栏」那么多（用户报过「菜单离鼠标太远」）。
 * 挂到 body 后 clientX/clientY 才是真正的视口坐标。
 *
 * 核对台的右键菜单与「新建音色」浮层共用这一个 action。
 */
export function portal(node: HTMLElement) {
  document.body.appendChild(node);
  return {
    destroy() {
      node.remove();
    },
  };
}
