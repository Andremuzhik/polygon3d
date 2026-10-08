document.querySelector("[data-burger]")?.addEventListener("click", (event) => {
  const nav = document.querySelector("[data-nav]");
  const open = nav?.classList.toggle("nav--open");
  event.currentTarget.setAttribute("aria-expanded", String(Boolean(open)));
});

// 3D-просмотрщик весит ~1 МБ, поэтому подгружаем его только по нажатию, а до этого показываем превью.
document.querySelectorAll("[data-viewer]").forEach((box) => {
  const button = box.querySelector("[data-viewer-start]");
  if (!button) return;
  const label = button.textContent;

  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Загрузка…";
    try {
      await import(box.dataset.module);
      const viewer = document.createElement("model-viewer");
      viewer.setAttribute("src", box.dataset.src);
      viewer.setAttribute("alt", box.dataset.alt);
      viewer.setAttribute("camera-controls", "");
      viewer.setAttribute("auto-rotate", "");
      viewer.setAttribute("shadow-intensity", "1");
      viewer.setAttribute("touch-action", "pan-y");
      box.querySelector(".viewer__stage").replaceChildren(viewer);
      box.querySelector("[data-viewer-hint]")?.removeAttribute("hidden");
    } catch (error) {
      console.error(error);
      button.disabled = false;
      button.textContent = "Не удалось загрузить. Повторить";
      setTimeout(() => (button.textContent = label), 4000);
    }
  });
});
