/**
 * FluTracker — Main application entry point.
 * Initializes all modules and orchestrates data flow between them.
 */

const App = {
    refreshInterval: null,
    hemisphereMode: 'calendar',
    cachedData: {},

    async init() {
        console.log('FluTracker initializing...');

        // Initialize modules
        await FluMap.init();
        Charts.init();
        Anomalies.init();
        Dashboard.init();

        // Hemisphere toggle
        document.querySelectorAll('#hemisphereToggle .toggle-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('#hemisphereToggle .toggle-btn').forEach(b =>
                    b.classList.remove('active')
                );
                e.target.classList.add('active');
                this.hemisphereMode = e.target.dataset.hemisphere;
                Charts.refresh();
            });
        });

        // Listen for country selection from map
        window.addEventListener('countrySelected', async (e) => {
            const { code, name } = e.detail;
            Charts.currentCountry = code;
            Dashboard.selectedCode = code;
            Dashboard.render();
            await Charts.refresh();

            // Load region data for map drill-down
            const regionData = await API.getCasesByRegion(code);
            if (regionData) {
                FluMap.showRegions(regionData);
            }
        });

        // Load all data
        await this.loadData();

        // Auto-refresh every 15 minutes
        this.refreshInterval = setInterval(() => this.loadData(), 15 * 60 * 1000);

        console.log('FluTracker ready');
    },

    /**
     * Load all dashboard data from API.
     */
    async loadData() {
        try {
            // Fetch all data in parallel
            const [
                countries,
                mapData,
                severityData,
                anomalies,
                summary,
            ] = await Promise.all([
                API.getCountries(),
                API.getMapGeoJSON(14),
                API.getSeverity(),
                API.getAnomalies(7),
                API.getSummary(),
            ]);

            // Update each module
            if (countries) {
                this.cachedData.countries = countries;
                Dashboard.update(countries, severityData);

                // Initialize comparison dropdowns
                const sorted = [...countries].sort((a, b) =>
                    (b.total_recent_cases || 0) - (a.total_recent_cases || 0)
                );
                Comparison.init(sorted);
            }

            if (mapData || severityData || anomalies) {
                FluMap.update(mapData, severityData, anomalies);
            }

            if (anomalies) {
                Anomalies.update(anomalies);
            }

            // Update last-updated timestamp
            if (summary) {
                document.getElementById('lastUpdated').textContent =
                    `Updated: ${Utils.timeAgo(summary.last_updated)}`;
            } else {
                document.getElementById('lastUpdated').textContent =
                    `Updated: ${new Date().toLocaleTimeString()}`;
            }

            // Draw initial chart
            await Charts.refresh();

        } catch (err) {
            console.error('Failed to load data', err);
            document.getElementById('lastUpdated').textContent = 'Error loading data';
        }
    },
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => App.init());
