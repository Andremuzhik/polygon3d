document.querySelector("[data-burger]")?.addEventListener("click", () => {
  document.querySelector("[data-nav]")?.classList.toggle("nav--open");
});
