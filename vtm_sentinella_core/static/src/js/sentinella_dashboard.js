/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat, formatMonetary } from "@web/views/fields/formatters";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";

const PALETTE = ["#176B87", "#3A7D44", "#F4B860", "#D95D39", "#457B9D", "#8E9AAF", "#CAD2C5"];
const STATE_COLOR = { verde: "#2d6a4f", amarillo: "#c78b00", rojo: "#bc4749" };

export class SentinellaDashboard extends Component {
    static template = "vtm_sentinella_core.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");

        this.altmanChartRef = useRef("altmanChart");
        this.barChartRef = useRef("barChart");
        this.pieChartRef = useRef("pieChart");
        this.chartInstances = {};
        this.animationFrame = null;

        this.state = useState({
            loading: true,
            computing: false,
            data: null,
            activeTab: "kpis",   // kpis | costs | recommendations
            chartNonce: 0,
            animatedKpis: {},
            selectedCompanyId: null,
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
        });

        useEffect(
            () => {
                if (this.state.data) {
                    this.renderCharts();
                }
                return () => this.destroyCharts();
            },
            () => [this.state.chartNonce, this.state.activeTab]
        );

        useEffect(
            () => {
                if (this.state.data) {
                    this.animateKpis();
                }
            },
            () => [this.state.data]
        );

        onWillUnmount(() => {
            this.destroyCharts();
            if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
        });
    }

    // ── Data loading ────────────────────────────────────────────────────────

    async loadData() {
        try {
            this.state.loading = true;
            const options = this.state.selectedCompanyId
                ? { company_id: this.state.selectedCompanyId }
                : {};
            const result = await this.orm.call(
                "sentinella.wizard",
                "get_sentinel_data",
                [],
                { options }
            );
            this.state.data = result;
            this.state.chartNonce += 1;
        } catch (e) {
            this.notification.add(
                e.message || _t("Error al cargar Sentinella."),
                { type: "danger", title: _t("Sentinella") }
            );
        } finally {
            this.state.loading = false;
        }
    }

    async computeNow() {
        try {
            this.state.computing = true;
            await this.orm.call("sentinella.wizard", "action_compute_now", [], {
                company_id: this.state.selectedCompanyId,
            });
            await this.loadData();
            this.notification.add(_t("Cómputo completado."), { type: "success" });
        } catch (e) {
            this.notification.add(e.message || _t("Error en cómputo."), { type: "danger" });
        } finally {
            this.state.computing = false;
        }
    }

    async changeCompany(companyId) {
        this.state.selectedCompanyId = companyId ? Number(companyId) : null;
        await this.loadData();
    }

    async updateRecommendation(recId, newState) {
        await this.orm.call("sentinella.wizard", "action_update_recommendation", [], {
            rec_id: recId,
            new_state: newState,
        });
        await this.loadData();
    }

    setTab(tab) {
        this.state.activeTab = tab;
    }

    // ── Formatters ──────────────────────────────────────────────────────────

    get currencyId() {
        return this.state.data?.meta?.currency_id;
    }

    formatMoney(value) {
        return formatMonetary(value || 0, { currencyId: this.currencyId });
    }

    formatNum(value, decimals = 1) {
        return formatFloat(value || 0, { digits: [0, decimals] });
    }

    kpiDisplay(kpi) {
        if (!kpi) return "";
        const animated = this.state.animatedKpis[kpi.key];
        const val = animated !== undefined ? animated : kpi.value;
        if (kpi.unit === "x") return `${this.formatNum(val, 2)}x`;
        if (kpi.unit === "días") return `${this.formatNum(val, 0)} días`;
        if (kpi.unit === "") return this.formatNum(val, 2);
        return this.formatNum(val, 1);
    }

    stateClass(state) {
        return state === "rojo" ? "is-red" : state === "amarillo" ? "is-yellow" : "is-green";
    }

    stateLabel(state) {
        return state === "rojo" ? "🔴 Crítico" : state === "amarillo" ? "🟡 Precaución" : "🟢 Saludable";
    }

    // ── KPI animation ───────────────────────────────────────────────────────

    animateKpis() {
        const kpis = this.state.data?.kpis || [];
        const targets = Object.fromEntries(kpis.map((k) => [k.key, k.value]));
        const starts = Object.fromEntries(kpis.map((k) => [k.key, 0]));
        const duration = 700;
        const startTime = performance.now();

        const ease = (t) => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

        const step = (now) => {
            const progress = Math.min((now - startTime) / duration, 1);
            const eased = ease(progress);
            const animated = {};
            for (const key of Object.keys(targets)) {
                animated[key] = starts[key] + (targets[key] - starts[key]) * eased;
            }
            this.state.animatedKpis = animated;
            if (progress < 1) {
                this.animationFrame = requestAnimationFrame(step);
            }
        };
        this.animationFrame = requestAnimationFrame(step);
    }

    // ── Chart rendering ─────────────────────────────────────────────────────

    destroyCharts() {
        for (const chart of Object.values(this.chartInstances)) {
            try { chart.destroy(); } catch {}
        }
        this.chartInstances = {};
    }

    renderCharts() {
        this.destroyCharts();
        if (this.state.activeTab === "kpis") {
            this._renderAltmanChart();
        } else if (this.state.activeTab === "costs") {
            this._renderBarChart();
            this._renderPieChart();
        }
    }

    _chartOpts(extra = {}) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 } } },
                tooltip: { mode: "index", intersect: false },
            },
            ...extra,
        };
    }

    _renderAltmanChart() {
        const el = this.altmanChartRef.el;
        if (!el || !this.state.data?.altman_history?.length) return;
        const history = this.state.data.altman_history;
        const labels = history.map((h) => h.date);
        const data = history.map((h) => h.z);

        this.chartInstances.altman = new window.Chart(el, {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        label: "Altman Z'",
                        data,
                        borderColor: "#176B87",
                        backgroundColor: "rgba(23,107,135,0.10)",
                        tension: 0.32,
                        fill: true,
                        pointRadius: 4,
                    },
                    {
                        label: "Zona Gris (2.9)",
                        data: labels.map(() => 2.9),
                        borderColor: "#F4B860",
                        borderDash: [6, 4],
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                    },
                    {
                        label: "Distress (1.23)",
                        data: labels.map(() => 1.23),
                        borderColor: "#bc4749",
                        borderDash: [6, 4],
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                    },
                ],
            },
            options: this._chartOpts({
                scales: {
                    y: { beginAtZero: false, grid: { color: "rgba(0,0,0,0.04)" } },
                    x: { grid: { display: false } },
                },
            }),
        });
    }

    _renderBarChart() {
        const el = this.barChartRef.el;
        if (!el || !this.state.data?.costs) return;
        const c = this.state.data.costs;
        const labels = c.pie_labels || [];
        const currentData = (this.state.data.costs.lines || [])
            .slice(0, 8)
            .map((l) => l.current);
        const prevData = (this.state.data.costs.lines || [])
            .slice(0, 8)
            .map((l) => l.prev);
        const lineLabels = (this.state.data.costs.lines || [])
            .slice(0, 8)
            .map((l) => l.account.length > 20 ? l.account.substring(0, 20) + "…" : l.account);

        this.chartInstances.bar = new window.Chart(el, {
            type: "bar",
            data: {
                labels: lineLabels,
                datasets: [
                    {
                        label: "Mes Actual",
                        data: currentData,
                        backgroundColor: "#176B87",
                        borderRadius: 6,
                    },
                    {
                        label: "Mes Anterior",
                        data: prevData,
                        backgroundColor: "#BFDBF7",
                        borderRadius: 6,
                    },
                ],
            },
            options: this._chartOpts({
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(0,0,0,0.04)" },
                        ticks: {
                            callback: (v) => {
                                if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
                                if (v >= 1000) return `${(v / 1000).toFixed(0)}K`;
                                return v;
                            },
                        },
                    },
                    x: { grid: { display: false } },
                },
            }),
        });
    }

    _renderPieChart() {
        const el = this.pieChartRef.el;
        if (!el || !this.state.data?.costs?.pie_labels?.length) return;
        const c = this.state.data.costs;

        this.chartInstances.pie = new window.Chart(el, {
            type: "pie",
            data: {
                labels: c.pie_labels,
                datasets: [{
                    data: c.pie_values,
                    backgroundColor: PALETTE,
                    borderWidth: 2,
                    borderColor: "#fff",
                }],
            },
            options: this._chartOpts(),
        });
    }
}

registry.category("actions").add("vtm_sentinella_core.dashboard", SentinellaDashboard);
