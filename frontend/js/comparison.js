/**
 * Comparison chart module for FluTracker.
 * Overlays trendlines from multiple countries for comparison.
 */

const Comparison = {
    selectedCountries: [],

    init(countries) {
        const selects = [
            document.getElementById('compareCountry1'),
            document.getElementById('compareCountry2'),
            document.getElementById('compareCountry3'),
        ];

        selects.forEach((sel, idx) => {
            sel.innerHTML = '<option value="">— Select —</option>';
            countries.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.code;
                opt.textContent = c.name;
                sel.appendChild(opt);
            });

            // Pre-select top 3 if available
            if (countries[idx]) {
                sel.value = countries[idx].code;
            }

            sel.addEventListener('change', () => this.onSelectionChange());
        });

        this.onSelectionChange();
    },

    onSelectionChange() {
        this.selectedCountries = [
            document.getElementById('compareCountry1').value,
            document.getElementById('compareCountry2').value,
            document.getElementById('compareCountry3').value,
        ].filter(Boolean);

        if (Charts.currentView === 'compare') {
            this.draw();
        }
    },

    async draw() {
        if (this.selectedCountries.length === 0) {
            Charts._drawEmpty('Select countries to compare');
            return;
        }

        const data = await API.compareTrends(this.selectedCountries);
        if (!data || !data.series) {
            Charts._drawEmpty('No comparison data available');
            return;
        }

        document.getElementById('chartTitle').textContent =
            `Compare: ${this.selectedCountries.join(' vs ')}`;

        const svg = Charts.svg;
        svg.selectAll('*').remove();

        const margin = Charts.margin;
        const width = Charts.width;
        const height = Charts.height;

        const g = svg.append('g')
            .attr('transform', `translate(${margin.left},${margin.top})`);

        const parseDate = d3.timeParse('%Y-%m-%d');

        // Prepare all series
        const allSeries = {};
        let allDates = [];
        let maxVal = 0;

        Object.entries(data.series).forEach(([code, points]) => {
            allSeries[code] = points.map(p => ({
                date: parseDate(p.date),
                value: p.cases_per_100k != null ? p.cases_per_100k : p.cases,
            }));
            allSeries[code].forEach(p => {
                allDates.push(p.date);
                if (p.value > maxVal) maxVal = p.value;
            });
        });

        if (allDates.length === 0) {
            Charts._drawEmpty('No data for selected countries');
            return;
        }

        const x = d3.scaleTime()
            .domain(d3.extent(allDates))
            .range([0, width]);

        const y = d3.scaleLinear()
            .domain([0, maxVal * 1.1])
            .nice()
            .range([height, 0]);

        // Grid
        g.append('g')
            .attr('class', 'grid')
            .call(d3.axisLeft(y).tickSize(-width).tickFormat(''));

        const line = d3.line()
            .x(d => x(d.date))
            .y(d => y(d.value))
            .curve(d3.curveMonotoneX)
            .defined(d => d.value != null);

        // Draw each country's line
        const codes = Object.keys(allSeries);
        codes.forEach((code, idx) => {
            const color = Utils.COMPARISON_COLORS[idx % Utils.COMPARISON_COLORS.length];

            g.append('path')
                .datum(allSeries[code])
                .attr('fill', 'none')
                .attr('stroke', color)
                .attr('stroke-width', 2.5)
                .attr('d', line);

            // Dots
            g.selectAll(`.dot-${code}`)
                .data(allSeries[code])
                .join('circle')
                .attr('cx', d => x(d.date))
                .attr('cy', d => y(d.value))
                .attr('r', 3)
                .attr('fill', color)
                .attr('stroke', '#1e2538')
                .attr('stroke-width', 1.5)
                .on('mouseover', (event, d) => {
                    Charts.tooltip
                        .style('display', 'block')
                        .html(`
                            <div class="tooltip-date">${code} — ${Utils.formatDate(d.date)}</div>
                            <div class="tooltip-value">${d.value.toFixed(1)} per 100k</div>
                        `)
                        .style('left', (event.offsetX + 15) + 'px')
                        .style('top', (event.offsetY - 10) + 'px');
                })
                .on('mouseout', () => {
                    Charts.tooltip.style('display', 'none');
                });
        });

        // Legend
        const legend = g.append('g')
            .attr('transform', `translate(${width - 100}, 5)`);

        codes.forEach((code, idx) => {
            const color = Utils.COMPARISON_COLORS[idx % Utils.COMPARISON_COLORS.length];
            const row = legend.append('g').attr('transform', `translate(0, ${idx * 18})`);
            row.append('line')
                .attr('x1', 0).attr('x2', 20).attr('y1', 0).attr('y2', 0)
                .attr('stroke', color).attr('stroke-width', 2.5);
            row.append('text')
                .attr('x', 26).attr('y', 4)
                .attr('fill', '#e8eaed').attr('font-size', '12px')
                .text(code);
        });

        // Axes
        g.append('g')
            .attr('class', 'axis')
            .attr('transform', `translate(0,${height})`)
            .call(d3.axisBottom(x).ticks(6).tickFormat(d3.timeFormat('%b %d')));

        g.append('g')
            .attr('class', 'axis')
            .call(d3.axisLeft(y).ticks(5).tickFormat(d => d.toFixed(0)));

        // Y-axis label
        g.append('text')
            .attr('transform', 'rotate(-90)')
            .attr('y', -50)
            .attr('x', -height / 2)
            .attr('text-anchor', 'middle')
            .attr('fill', '#9aa0a6')
            .attr('font-size', '11px')
            .text('Cases per 100k');
    },
};
