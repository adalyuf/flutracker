/**
 * D3 chart module for FluTracker.
 * Renders trendlines, subtype stacked areas, and historical overlays.
 */

const Charts = {
    svg: null,
    margin: { top: 20, right: 30, bottom: 40, left: 60 },
    width: 0,
    height: 0,
    currentView: 'trend',
    currentCountry: null,
    tooltip: null,

    init() {
        this.svg = d3.select('#mainChart');
        this.tooltip = d3.select('#chartContainer')
            .append('div')
            .attr('class', 'chart-tooltip')
            .style('display', 'none');

        this._updateDimensions();
        window.addEventListener('resize', Utils.debounce(() => {
            this._updateDimensions();
            this.refresh();
        }, 250));

        // Chart view buttons
        document.querySelectorAll('.chart-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.chart-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.currentView = e.target.dataset.view;
                this.refresh();

                // Show/hide compare selector
                document.getElementById('compareSelector').style.display =
                    this.currentView === 'compare' ? 'flex' : 'none';
            });
        });
    },

    _updateDimensions() {
        const container = document.getElementById('chartContainer');
        const rect = container.getBoundingClientRect();
        this.width = rect.width - this.margin.left - this.margin.right;
        this.height = rect.height - this.margin.top - this.margin.bottom;
    },

    /**
     * Refresh current chart view with latest data.
     */
    async refresh() {
        this._updateDimensions();
        switch (this.currentView) {
            case 'trend':
                await this.drawTrendline();
                break;
            case 'subtype':
                await this.drawSubtypeChart();
                break;
            case 'historical':
                await this.drawHistoricalOverlay();
                break;
            case 'forecast':
                await this.drawForecast();
                break;
            case 'compare':
                await Comparison.draw();
                break;
        }
    },

    /**
     * Draw the main trendline chart.
     */
    async drawTrendline() {
        const data = this.currentCountry
            ? await API.getTrends(this.currentCountry)
            : await API.getGlobalTrends();

        if (!data || !data.data || data.data.length === 0) {
            this._drawEmpty('No trend data available');
            return;
        }

        const title = this.currentCountry
            ? `Trend: ${this.currentCountry}`
            : 'Global Trend';
        document.getElementById('chartTitle').textContent = title;

        this.svg.selectAll('*').remove();

        const g = this.svg
            .append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        const parseDate = d3.timeParse('%Y-%m-%d');
        const points = data.data.map(d => ({
            date: parseDate(d.date),
            cases: d.cases,
            per100k: d.cases_per_100k,
        }));

        const x = d3.scaleTime()
            .domain(d3.extent(points, d => d.date))
            .range([0, this.width]);

        const y = d3.scaleLinear()
            .domain([0, d3.max(points, d => d.cases) * 1.1])
            .nice()
            .range([this.height, 0]);

        // Grid lines
        g.append('g')
            .attr('class', 'grid')
            .call(d3.axisLeft(y).tickSize(-this.width).tickFormat(''));

        // Area
        const area = d3.area()
            .x(d => x(d.date))
            .y0(this.height)
            .y1(d => y(d.cases))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(points)
            .attr('class', 'trend-area')
            .attr('d', area);

        // Line
        const line = d3.line()
            .x(d => x(d.date))
            .y(d => y(d.cases))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(points)
            .attr('class', 'trend-line')
            .attr('d', line);

        // Dots
        g.selectAll('.dot')
            .data(points)
            .join('circle')
            .attr('cx', d => x(d.date))
            .attr('cy', d => y(d.cases))
            .attr('r', 4)
            .attr('fill', '#00d4aa')
            .attr('stroke', '#1e2538')
            .attr('stroke-width', 2)
            .on('mouseover', (event, d) => {
                this.tooltip
                    .style('display', 'block')
                    .html(`
                        <div class="tooltip-date">${Utils.formatDate(d.date)}</div>
                        <div class="tooltip-value">${Utils.formatNumber(d.cases)} cases</div>
                    `)
                    .style('left', (event.offsetX + 15) + 'px')
                    .style('top', (event.offsetY - 10) + 'px');
            })
            .on('mouseout', () => {
                this.tooltip.style('display', 'none');
            });

        // Axes
        g.append('g')
            .attr('class', 'axis')
            .attr('transform', `translate(0,${this.height})`)
            .call(d3.axisBottom(x).ticks(6).tickFormat(d3.timeFormat('%b %d')));

        g.append('g')
            .attr('class', 'axis')
            .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(',.0f')));
    },

    /**
     * Draw subtype stacked area chart.
     */
    async drawSubtypeChart() {
        const data = await API.getFluTypes(this.currentCountry, 84); // 12 weeks
        if (!data || !data.breakdown || data.breakdown.length === 0) {
            this._drawEmpty('No subtype data available');
            return;
        }

        document.getElementById('chartTitle').textContent =
            `Flu Subtypes${this.currentCountry ? ': ' + this.currentCountry : ''}`;

        this.svg.selectAll('*').remove();

        const g = this.svg
            .append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        // Draw as a horizontal bar chart since we have aggregate data
        const y = d3.scaleBand()
            .domain(data.breakdown.map(d => d.flu_type))
            .range([0, this.height])
            .padding(0.2);

        const x = d3.scaleLinear()
            .domain([0, d3.max(data.breakdown, d => d.percentage)])
            .range([0, this.width]);

        g.selectAll('.bar')
            .data(data.breakdown)
            .join('rect')
            .attr('y', d => y(d.flu_type))
            .attr('x', 0)
            .attr('height', y.bandwidth())
            .attr('width', d => x(d.percentage))
            .attr('fill', d => Utils.fluTypeColor(d.flu_type))
            .attr('rx', 3);

        // Labels
        g.selectAll('.bar-label')
            .data(data.breakdown)
            .join('text')
            .attr('y', d => y(d.flu_type) + y.bandwidth() / 2)
            .attr('x', d => x(d.percentage) + 8)
            .attr('dy', '0.35em')
            .attr('fill', '#9aa0a6')
            .attr('font-size', '12px')
            .text(d => `${d.percentage.toFixed(1)}% (${Utils.formatNumber(d.count)})`);

        g.append('g')
            .attr('class', 'axis')
            .call(d3.axisLeft(y))
            .selectAll('text')
            .attr('fill', '#e8eaed');
    },

    /**
     * Draw historical overlay — current season vs past seasons.
     */
    async drawHistoricalOverlay() {
        const result = await API.getHistoricalSeasons(this.currentCountry, 5);

        if (!result || !result.current_season || result.current_season.data.length === 0) {
            this._drawEmpty('No historical data available');
            return;
        }

        document.getElementById('chartTitle').textContent =
            `Historical Comparison${this.currentCountry ? ': ' + this.currentCountry : ''}`;

        this.svg.selectAll('*').remove();

        const g = this.svg
            .append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        const currentData = result.current_season.data;
        const pastSeasons = result.past_seasons || [];

        // Find max week index across all seasons for x domain
        let maxWeek = 0;
        const allSeasons = [currentData, ...pastSeasons.map(s => s.data)];
        allSeasons.forEach(s => {
            s.forEach(d => {
                const w = parseInt(d.date);
                if (w > maxWeek) maxWeek = w;
            });
        });

        const x = d3.scaleLinear()
            .domain([0, Math.max(maxWeek, 51)])
            .range([0, this.width]);

        // Find max cases across all seasons for y domain
        let maxCases = 0;
        allSeasons.forEach(s => {
            s.forEach(d => { if (d.cases > maxCases) maxCases = d.cases; });
        });

        const y = d3.scaleLinear()
            .domain([0, maxCases * 1.2])
            .nice()
            .range([this.height, 0]);

        // Grid
        g.append('g')
            .attr('class', 'grid')
            .call(d3.axisLeft(y).tickSize(-this.width).tickFormat(''));

        const line = d3.line()
            .x(d => x(parseInt(d.date)))
            .y(d => y(d.cases))
            .curve(d3.curveMonotoneX);

        // Historical range band (min/max across past seasons)
        if (pastSeasons.length > 0) {
            // Build a map of week -> [cases values] across past seasons
            const weekMap = {};
            pastSeasons.forEach(s => {
                s.data.forEach(d => {
                    const w = parseInt(d.date);
                    if (!weekMap[w]) weekMap[w] = [];
                    weekMap[w].push(d.cases);
                });
            });

            const bandData = Object.keys(weekMap)
                .map(Number)
                .sort((a, b) => a - b)
                .map(w => ({
                    week: w,
                    min: d3.min(weekMap[w]),
                    max: d3.max(weekMap[w]),
                }));

            const area = d3.area()
                .x(d => x(d.week))
                .y0(d => y(d.min))
                .y1(d => y(d.max))
                .curve(d3.curveMonotoneX);

            g.append('path')
                .datum(bandData)
                .attr('d', area)
                .attr('fill', '#4a9eff')
                .attr('opacity', 0.08);

            // Historical season lines
            const historicalColors = ['#5f6368', '#4a4f5a', '#3a3f4a', '#2a2f3a', '#6b7280'];
            pastSeasons.forEach((season, idx) => {
                if (season.data.length > 0) {
                    g.append('path')
                        .datum(season.data)
                        .attr('class', 'historical-line')
                        .attr('d', line)
                        .attr('stroke', historicalColors[idx % historicalColors.length]);
                }
            });
        }

        // Current season (bold line)
        if (currentData.length > 0) {
            g.append('path')
                .datum(currentData)
                .attr('class', 'trend-line')
                .attr('d', line);
        }

        // Legend
        const legendData = [
            { label: result.current_season.label, color: '#00d4aa', dash: '' },
            ...pastSeasons.map((s, i) => ({
                label: s.label,
                color: ['#5f6368', '#4a4f5a', '#3a3f4a', '#2a2f3a', '#6b7280'][i % 5],
                dash: '4 2',
            })),
        ];
        const legend = g.append('g')
            .attr('transform', `translate(${this.width - 160}, 5)`);

        legendData.forEach((d, i) => {
            const row = legend.append('g').attr('transform', `translate(0, ${i * 18})`);
            row.append('line')
                .attr('x1', 0).attr('x2', 20).attr('y1', 0).attr('y2', 0)
                .attr('stroke', d.color).attr('stroke-width', 2)
                .attr('stroke-dasharray', d.dash);
            row.append('text')
                .attr('x', 26).attr('y', 4)
                .attr('fill', '#9aa0a6').attr('font-size', '11px')
                .text(d.label);
        });

        // Axes
        g.append('g')
            .attr('class', 'axis')
            .attr('transform', `translate(0,${this.height})`)
            .call(d3.axisBottom(x)
                .tickValues([0, 4, 8, 13, 17, 21, 26, 30, 34, 39, 43, 47, 51]
                    .filter(w => w <= Math.max(maxWeek, 51)))
                .tickFormat(i => `W${i + 1}`));

        g.append('g')
            .attr('class', 'axis')
            .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(',.0f')));
    },

    /**
     * Draw empty state message.
     */
    _drawEmpty(message) {
        this.svg.selectAll('*').remove();
        this.svg.append('text')
            .attr('x', '50%')
            .attr('y', '50%')
            .attr('text-anchor', 'middle')
            .attr('fill', '#5f6368')
            .attr('font-size', '14px')
            .text(message);
    },
};
