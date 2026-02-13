/**
 * Mini stacked-area charts for the dashboard: Clade Trends & Subtype Trends.
 * Both scoped to 1 year.
 */

const MiniCharts = {
    tooltipEl: null,

    init() {
        this.tooltipEl = document.createElement('div');
        this.tooltipEl.className = 'geno-tooltip';
        this.tooltipEl.style.display = 'none';
        document.body.appendChild(this.tooltipEl);

        window.addEventListener('resize', Utils.debounce(() => this.refresh(), 250));
    },

    // Clade chart: cool/green-blue tones
    CLADE_PALETTE: [
        '#00d4aa', '#4a9eff', '#8a7dff', '#59b0ff', '#7dd87d',
        '#2ec4b6', '#48bfe3', '#a5b4fc',
    ],

    // Subtype chart: warm amber-red tones
    SUBTYPE_PALETTE: [
        '#ff8c00', '#ff6b6b', '#ffd700', '#e879f9', '#f97316',
        '#fb7185', '#fbbf24', '#c084fc',
    ],

    async refresh() {
        const [cladeData, subtypeData] = await Promise.all([
            API.getGenomicsTrends(1, 6),
            API.getFluTypeTrends(null, 365, 6),
        ]);
        this.drawStackedArea('#cladeChart', cladeData, 'month', 'clade', 'sequences', this.CLADE_PALETTE);
        this.drawStackedArea('#subtypeChart', subtypeData, 'week', 'flu_type', 'cases', this.SUBTYPE_PALETTE);
    },

    /**
     * Generic stacked area renderer.
     * @param {string} selector - SVG selector
     * @param {object} data - API response with .data array
     * @param {string} timeField - key for time bucket in each row
     * @param {string} groupField - key for category (clade or flu_type)
     * @param {string} valueField - key for numeric value
     */
    drawStackedArea(selector, data, timeField, groupField, valueField, palette) {
        const svg = d3.select(selector);
        svg.selectAll('*').remove();

        if (!data || !data.data || data.data.length === 0) {
            svg.append('text')
                .attr('x', '50%').attr('y', '50%')
                .attr('text-anchor', 'middle')
                .attr('fill', '#5f6368').attr('font-size', '13px')
                .text('No data available');
            return;
        }

        const rect = svg.node().getBoundingClientRect();
        const margin = { top: 8, right: 12, bottom: 28, left: 44 };
        const width = rect.width - margin.left - margin.right;
        const height = rect.height - margin.top - margin.bottom;
        if (width <= 0 || height <= 0) return;

        const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

        const parseDate = d3.timeParse('%Y-%m-%d');
        const rows = data.data.map(d => ({
            date: parseDate(d[timeField]),
            group: d[groupField],
            value: d[valueField],
        })).filter(d => d.date);

        const dates = Array.from(new Set(rows.map(d => +d.date)))
            .map(t => new Date(t)).sort((a, b) => a - b);
        const groups = data.top_clades || data.top_types || Array.from(new Set(rows.map(d => d.group)));
        // Include "Other" if present
        const allGroups = [...groups];
        if (rows.some(d => d.group === 'Other') && !allGroups.includes('Other')) {
            allGroups.push('Other');
        }

        // Build lookup table
        const table = {};
        dates.forEach(d => { table[+d] = {}; });
        rows.forEach(r => {
            if (table[+r.date]) {
                table[+r.date][r.group] = (table[+r.date][r.group] || 0) + r.value;
            }
        });

        const stackedInput = dates.map(d => {
            const item = { date: d };
            allGroups.forEach(g => { item[g] = table[+d][g] || 0; });
            return item;
        });

        const stack = d3.stack().keys(allGroups)(stackedInput);

        const x = d3.scaleTime().domain(d3.extent(dates)).range([0, width]);
        const y = d3.scaleLinear()
            .domain([0, d3.max(stackedInput, d => allGroups.reduce((s, g) => s + d[g], 0)) || 1])
            .nice()
            .range([height, 0]);

        const color = d3.scaleOrdinal().domain(allGroups).range(palette);

        const area = d3.area()
            .x(d => x(d.data.date))
            .y0(d => y(d[0]))
            .y1(d => y(d[1]))
            .curve(d3.curveMonotoneX);

        const bisect = d3.bisector(d => d.date).left;
        const self = this;

        g.selectAll('.layer')
            .data(stack)
            .join('path')
            .attr('d', area)
            .attr('fill', d => color(d.key))
            .attr('opacity', 0.85)
            .style('cursor', 'pointer')
            .on('mousemove', function (event, series) {
                const [mx] = d3.pointer(event, g.node());
                const date = x.invert(mx);
                const idx = Math.max(0, Math.min(stackedInput.length - 1, bisect(stackedInput, date)));
                const row = stackedInput[idx];
                self._showTooltip(
                    event.clientX, event.clientY,
                    series.key,
                    d3.timeFormat('%Y-%m-%d')(row.date),
                    Utils.formatNumber(row[series.key] || 0),
                );
            })
            .on('mouseleave', () => self._hideTooltip());

        // Axes
        g.append('g')
            .attr('transform', `translate(0,${height})`)
            .call(d3.axisBottom(x).ticks(6).tickFormat(d3.timeFormat('%b')))
            .selectAll('text').attr('fill', '#9aa0a6');

        g.append('g')
            .call(d3.axisLeft(y).ticks(4).tickFormat(d3.format(',~s')))
            .selectAll('text').attr('fill', '#9aa0a6');

        // HTML legend below chart
        const container = svg.node().closest('.mini-chart-panel');
        let legendEl = container.querySelector('.mini-legend');
        if (!legendEl) {
            legendEl = document.createElement('div');
            legendEl.className = 'mini-legend';
            container.appendChild(legendEl);
        }
        legendEl.innerHTML = allGroups.slice(0, 8).map(name =>
            `<span class="mini-legend-item">` +
            `<span class="mini-legend-swatch" style="background:${color(name)}"></span>` +
            `${name}</span>`
        ).join('');
    },

    _showTooltip(x, y, label, time, value) {
        this.tooltipEl.innerHTML = `
            <div class="k">${label}</div>
            <div class="v">${time}</div>
            <div class="k" style="margin-top:4px;">Count</div>
            <div class="v">${value}</div>
        `;
        this.tooltipEl.style.display = 'block';
        this.tooltipEl.style.left = `${x + 14}px`;
        this.tooltipEl.style.top = `${y + 14}px`;
    },

    _hideTooltip() {
        this.tooltipEl.style.display = 'none';
    },
};
