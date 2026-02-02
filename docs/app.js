(function () {
  const CATLIST_URL = "https://raw.githubusercontent.com/yazelin/catime/main/catlist.json";
  const PAGE_SIZE = 20;

  let allCats = [];
  let filtered = [];
  let loaded = 0;
  let loading = false;

  const gallery = document.getElementById("gallery");
  const endMsg = document.getElementById("end-msg");
  const modelSelect = document.getElementById("model-filter");
  const dateInput = document.getElementById("date-filter");
  const dateClear = document.getElementById("date-clear");
  const timelineList = document.getElementById("timeline-list");
  const timelineNav = document.getElementById("timeline");
  const timelineToggle = document.getElementById("timeline-toggle");
  const lightbox = document.getElementById("lightbox");
  const lbImg = document.getElementById("lb-img");
  const lbInfo = document.getElementById("lb-info");
  const lbClose = document.getElementById("lb-close");

  // Fetch data
  fetch(CATLIST_URL)
    .then(r => r.json())
    .then(data => {
      allCats = data.filter(c => c.status !== "failed").reverse(); // newest first
      populateModels();
      buildTimeline();
      applyFilter();
    })
    .catch(err => {
      gallery.innerHTML = `<p style="padding:2rem;color:var(--pink)">Failed to load cat list: ${err.message}</p>`;
    });

  function populateModels() {
    const models = [...new Set(allCats.map(c => c.model).filter(Boolean))].sort();
    models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m; opt.textContent = m;
      modelSelect.appendChild(opt);
    });
  }

  function buildTimeline() {
    const map = {};
    allCats.forEach(c => {
      const [date] = c.timestamp.split(" ");
      const [y, m] = date.split("-");
      if (!map[y]) map[y] = new Set();
      map[y].add(m);
    });
    let html = "";
    Object.keys(map).sort().reverse().forEach(y => {
      html += `<div class="year">${y}</div>`;
      [...map[y]].sort().reverse().forEach(m => {
        html += `<a href="#" data-ym="${y}-${m}">${y}-${m}</a>`;
      });
    });
    timelineList.innerHTML = html;
  }

  // Filter
  function applyFilter() {
    const model = modelSelect.value;
    const date = dateInput.value; // "YYYY-MM-DD" or ""
    filtered = allCats.filter(c => {
      if (model && c.model !== model) return false;
      if (date && !c.timestamp.startsWith(date)) return false;
      return true;
    });
    loaded = 0;
    gallery.innerHTML = "";
    endMsg.classList.add("hidden");
    loadMore();
  }

  modelSelect.addEventListener("change", applyFilter);
  dateInput.addEventListener("change", applyFilter);
  dateClear.addEventListener("click", () => { dateInput.value = ""; applyFilter(); });

  // Render cards
  function loadMore() {
    if (loading || loaded >= filtered.length) return;
    loading = true;
    const slice = filtered.slice(loaded, loaded + PAGE_SIZE);
    let lastMonth = "";
    if (loaded > 0) {
      const prev = filtered[loaded - 1];
      lastMonth = prev.timestamp.slice(0, 7);
    }
    const frag = document.createDocumentFragment();
    slice.forEach(cat => {
      const month = cat.timestamp.slice(0, 7);
      if (month !== lastMonth) {
        const sep = document.createElement("div");
        sep.className = "month-sep";
        sep.id = `m-${month}`;
        sep.textContent = month;
        frag.appendChild(sep);
        lastMonth = month;
      }
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <img src="${cat.url}" alt="Cat #${cat.number}" loading="lazy">
        <div class="card-info">
          <div class="time">#${cat.number} &middot; ${cat.timestamp}</div>
          ${cat.model ? `<span class="model">${cat.model}</span>` : ""}
        </div>`;
      card.addEventListener("click", () => openLightbox(cat));
      frag.appendChild(card);
    });
    gallery.appendChild(frag);
    loaded += slice.length;
    loading = false;
    if (loaded >= filtered.length) endMsg.classList.remove("hidden");
  }

  // Infinite scroll
  const observer = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) loadMore();
  }, { rootMargin: "200px" });
  observer.observe(endMsg);

  // Timeline click
  timelineList.addEventListener("click", e => {
    e.preventDefault();
    const ym = e.target.dataset.ym;
    if (!ym) return;
    // Ensure enough cards are loaded
    const idx = filtered.findIndex(c => c.timestamp.startsWith(ym));
    if (idx === -1) return;
    while (loaded <= idx && loaded < filtered.length) loadMore();
    const el = document.getElementById(`m-${ym}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    if (window.innerWidth <= 1024) timelineNav.classList.remove("open");
  });

  // Timeline toggle (mobile)
  timelineToggle.addEventListener("click", () => timelineNav.classList.toggle("open"));

  // Lightbox
  function openLightbox(cat) {
    lbImg.src = cat.url;
    lbInfo.textContent = `#${cat.number} \u00b7 ${cat.timestamp} \u00b7 ${cat.model || ""}`;
    lightbox.classList.remove("hidden");
  }
  lbClose.addEventListener("click", () => lightbox.classList.add("hidden"));
  lightbox.addEventListener("click", e => { if (e.target === lightbox) lightbox.classList.add("hidden"); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") lightbox.classList.add("hidden"); });


})();
