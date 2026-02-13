const GenomicsPage = {
    state: {
        years: 10,
        country: "",
        topN: 6,
        countries: [],
    },
    tooltipEl: null,
    pinnedClade: null,

    async init() {
        this.tooltipEl = document.createElement("div");
        this.tooltipEl.className = "geno-tooltip";
        this.tooltipEl.style.display = "none";
        document.body.appendChild(this.tooltipEl);
        this.bindEvents();
        await this.loadCountries();
        await this.refresh();
    },

    bindEvents() {
        document.getElementById("yearsSelect").addEventListener("change", async (e) => {
            this.state.years = Number(e.target.value);
            await this.refresh();
        });
        document.getElementById("countrySelect").addEventListener("change", async (e) => {
            this.state.country = e.target.value;
            await this.refresh();
        });
        document.getElementById("topNSelect").addEventListener("change", async (e) => {
            this.state.topN = Number(e.target.value);
            await this.refresh();
        });
        window.addEventListener("resize", () => this.drawTrend(this.lastTrend));
    },

    async fetchJSON(path, params = {}) {
        const url = new URL(`/api${path}`, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, String(v));
        });
        const resp = await fetch(url);
        if (!resp.ok) return null;
        return await resp.json();
    },

    async loadCountries() {
        const res = await this.fetchJSON("/genomics/countries", { years: 10, limit: 250 });
        this.state.countries = res?.countries || [];
        const sel = document.getElementById("countrySelect");
        sel.innerHTML = '<option value="">Global</option>';
        this.state.countries.forEach((c) => {
            const opt = document.createElement("option");
            opt.value = c.country_code;
            opt.textContent = `${c.country_name} (${c.country_code})`;
            sel.appendChild(opt);
        });
    },

    async refresh() {
        const params = { years: this.state.years };
        const [summary, trends, countries] = await Promise.all([
            this.fetchJSON("/genomics/summary", params),
            this.fetchJSON("/genomics/trends", {
                ...params,
                country: this.state.country || null,
                top_n: this.state.topN,
            }),
            this.fetchJSON("/genomics/countries", params),
        ]);
        this.renderSummary(summary);
        this.renderCountries(countries);
        this.lastTrend = trends;
        this.drawTrend(trends);
    },

    renderSummary(summary) {
        document.getElementById("kpiSequences").textContent = this.formatNum(summary?.total_sequences || 0);
        document.getElementById("kpiCountries").textContent = this.formatNum(summary?.countries_tracked || 0);
        document.getElementById("kpiClades").textContent = this.formatNum(summary?.unique_clades || 0);
        document.getElementById("kpiDominant").textContent = summary?.dominant_clade || "-";
    },

    renderCountries(countriesData) {
        const body = document.getElementById("countriesBody");
        const rows = countriesData?.countries || [];
        if (!rows.length) {
            body.innerHTML = "<tr><td colspan='4'>No sequence data</td></tr>";
            return;
        }
        body.innerHTML = rows.slice(0, 20).map((r) => `
            <tr>
                <td>${r.country_name} (${r.country_code})</td>
                <td>${this.formatNum(r.sequences)}</td>
                <td>${r.unique_clades}</td>
                <td>${r.last_sample_date ? r.last_sample_date.slice(0, 10) : "-"}</td>
            </tr>
        `).join("");
    },

    drawTrend(trendsData) {
        const svg = d3.select("#trendChart");
        svg.selectAll("*").remove();
        if (!trendsData || !trendsData.data || !trendsData.data.length) return;

        const rect = document.getElementById("trendChart").getBoundingClientRect();
        const margin = { top: 10, right: 16, bottom: 30, left: 54 };
        const width = rect.width - margin.left - margin.right;
        const height = rect.height - margin.top - margin.bottom;
        const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

        const parseMonth = d3.timeParse("%Y-%m-%d");
        const rows = trendsData.data.map((d) => ({
            date: parseMonth(d.month),
            clade: d.clade,
            sequences: d.sequences,
        }));
        const months = Array.from(new Set(rows.map((d) => +d.date))).map((t) => new Date(t)).sort((a, b) => a - b);
        const clades = Array.from(new Set(rows.map((d) => d.clade)));

        const table = {};
        months.forEach((m) => { table[+m] = {}; });
        rows.forEach((r) => { table[+r.date][r.clade] = r.sequences; });
        const stackedInput = months.map((m) => {
            const item = { date: m };
            clades.forEach((c) => { item[c] = table[+m][c] || 0; });
            return item;
        });

        const stack = d3.stack().keys(clades)(stackedInput);
        const x = d3.scaleTime().domain(d3.extent(months)).range([0, width]);
        const y = d3.scaleLinear()
            .domain([0, d3.max(stackedInput, (d) => clades.reduce((s, c) => s + d[c], 0)) || 1])
            .nice()
            .range([height, 0]);
        const color = d3.scaleOrdinal(clades, [
            "#00d4aa", "#4a9eff", "#ff8c00", "#ffd700", "#ff6b6b", "#8a7dff", "#7dd87d", "#59b0ff",
        ]);
        const bisect = d3.bisector((d) => d.date).left;

        const area = d3.area()
            .x((d) => x(d.data.date))
            .y0((d) => y(d[0]))
            .y1((d) => y(d[1]))
            .curve(d3.curveMonotoneX);

        const layers = g.selectAll(".layer")
            .data(stack)
            .join("path")
            .attr("d", area)
            .attr("fill", (d) => color(d.key))
            .attr("opacity", (d) => this.pinnedClade && d.key !== this.pinnedClade ? 0.25 : 0.85)
            .style("cursor", "pointer")
            .on("mouseenter", (event, series) => {
                this.showTooltip(event.clientX, event.clientY, series.key, "-", "-");
            })
            .on("mousemove", (event, series) => {
                const [mx] = d3.pointer(event, g.node());
                const date = x.invert(mx);
                const idx = Math.max(0, Math.min(stackedInput.length - 1, bisect(stackedInput, date) - 1));
                const row = stackedInput[idx];
                this.showTooltip(
                    event.clientX,
                    event.clientY,
                    series.key,
                    d3.timeFormat("%Y-%m")(row.date),
                    row[series.key] || 0,
                );
            })
            .on("mouseleave", () => {
                if (!this.pinnedClade) this.hideTooltip();
            })
            .on("click", (event, series) => {
                event.stopPropagation();
                this.togglePinnedClade(series.key, layers, legendRows);
                if (!this.pinnedClade) {
                    this.hideTooltip();
                    return;
                }
                this.showTooltip(event.clientX, event.clientY, series.key, "Pinned", "click to unpin");
            });

        g.append("g")
            .attr("transform", `translate(0,${height})`)
            .call(d3.axisBottom(x).ticks(8).tickFormat(d3.timeFormat("%Y-%m")));
        g.append("g")
            .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(",")));

        const legend = svg.append("g").attr("transform", "translate(14,16)");
        const legendRows = [];
        clades.slice(0, 8).forEach((clade, i) => {
            const row = legend.append("g")
                .attr("transform", `translate(0,${i * 16})`)
                .style("cursor", "pointer")
                .on("mouseenter", (event) => {
                    this.showTooltip(event.clientX, event.clientY, clade, "Legend", "hover");
                })
                .on("mouseleave", () => {
                    if (!this.pinnedClade) this.hideTooltip();
                })
                .on("click", (event) => {
                    event.stopPropagation();
                    this.togglePinnedClade(clade, layers, legendRows);
                    if (!this.pinnedClade) {
                        this.hideTooltip();
                        return;
                    }
                    this.showTooltip(event.clientX, event.clientY, clade, "Pinned", "click to unpin");
                });
            row.append("rect").attr("width", 10).attr("height", 10).attr("fill", color(clade));
            row.append("text")
                .attr("x", 14)
                .attr("y", 9)
                .attr("fill", "#97a1ad")
                .attr("font-size", "11px")
                .text(clade);
            legendRows.push({ clade, row });
        });

        svg.on("click", () => {
            if (!this.pinnedClade) return;
            this.pinnedClade = null;
            layers.attr("opacity", 0.85);
            legendRows.forEach((entry) => {
                entry.row.select("text").attr("fill", "#97a1ad").attr("font-weight", "400");
            });
            this.hideTooltip();
        });
    },

    togglePinnedClade(clade, layers, legendRows) {
        this.pinnedClade = this.pinnedClade === clade ? null : clade;
        layers.attr("opacity", (d) => this.pinnedClade && d.key !== this.pinnedClade ? 0.25 : 0.85);
        legendRows.forEach((entry) => {
            const active = this.pinnedClade === entry.clade;
            entry.row.select("text")
                .attr("fill", active ? "#e8eaed" : "#97a1ad")
                .attr("font-weight", active ? "700" : "400");
        });
    },

    showTooltip(x, y, clade, month, sequences) {
        this.tooltipEl.innerHTML = `
            <div class="k">Clade</div><div class="v">${clade}</div>
            <div class="k" style="margin-top:6px;">Month</div><div class="v">${month}</div>
            <div class="k" style="margin-top:6px;">Sequences</div><div class="v">${sequences}</div>
        `;
        this.tooltipEl.style.display = "block";
        this.tooltipEl.style.left = `${x + 14}px`;
        this.tooltipEl.style.top = `${y + 14}px`;
    },

    hideTooltip() {
        this.tooltipEl.style.display = "none";
    },

    formatNum(value) {
        return new Intl.NumberFormat().format(value);
    },
};

document.addEventListener("DOMContentLoaded", () => GenomicsPage.init());
