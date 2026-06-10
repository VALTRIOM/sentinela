/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat, formatMonetary } from "@web/views/fields/formatters";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Chart, registerables } from "chart.js";
Chart.register(...registerables);

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState, xml } from "@odoo/owl";

const PALETTE = ["#176B87", "#3A7D44", "#F4B860", "#D95D39", "#457B9D", "#8E9AAF", "#CAD2C5"];
const STATE_COLOR = { verde: "#2d6a4f", amarillo: "#c78b00", rojo: "#bc4749" };

const TEMPLATE = xml`
<div class="o_sentinella">

    <!-- Hero -->
    <div class="o_sentinella__hero">
        <div class="o_sentinella__hero-left">
            <div class="eyebrow">INTELIGENCIA EMPRESARIAL</div>
            <h1>Sentinella</h1>
            <div class="meta" t-if="state.data">
                <span>
                    <t t-if="state.data.meta.company_name">
                        <b t-esc="state.data.meta.company_name"/>
                    </t>
                </span>
                <span t-if="state.data.meta.date">
                    Actualizado: <t t-esc="state.data.meta.date"/>
                </span>
                <span t-if="state.data.overall_state"
                      t-attf-class="state-badge {{ stateClass(state.data.overall_state) }}">
                    <t t-esc="stateLabel(state.data.overall_state)"/>
                </span>
            </div>
        </div>
        <div class="o_sentinella__hero-actions">
            <t t-if="state.data &amp;&amp; state.data.companies &amp;&amp; state.data.companies.length > 1">
                <select class="form-select form-select-sm" style="min-width:160px;"
                        t-on-change="(e) => this.changeCompany(e.target.value)">
                    <option value="">Todas las empresas</option>
                    <t t-foreach="state.data.companies" t-as="co" t-key="co.id">
                        <option t-att-value="co.id" t-esc="co.name"
                                t-att-selected="state.selectedCompanyId === co.id"/>
                    </t>
                </select>
            </t>
            <button class="sl-btn sl-btn-outline" t-on-click="loadData"
                    t-att-disabled="state.loading">
                <i class="fa fa-refresh"/> Actualizar
            </button>
            <button class="sl-btn sl-btn-primary" t-on-click="computeNow"
                    t-att-disabled="state.computing || state.loading">
                <i class="fa fa-bolt"/>
                <t t-if="state.computing">Calculando...</t>
                <t t-else="">Calcular Ahora</t>
            </button>
        </div>
    </div>

    <!-- Tabs -->
    <div class="o_sentinella__tabs">
        <button t-attf-class="tab-btn {{ state.activeTab === 'kpis' ? 'active' : '' }}"
                t-on-click="() => this.setTab('kpis')">
            Semaforo Financiero
        </button>
        <button t-attf-class="tab-btn {{ state.activeTab === 'costs' ? 'active' : '' }}"
                t-on-click="() => this.setTab('costs')">
            Analisis de Costos
        </button>
        <button t-attf-class="tab-btn {{ state.activeTab === 'recommendations' ? 'active' : '' }}"
                t-on-click="() => this.setTab('recommendations')">
            Recomendaciones
            <t t-if="state.data &amp;&amp; state.data.recommendations &amp;&amp; state.data.recommendations.length">
                <span class="badge bg-danger ms-1" t-esc="state.data.recommendations.length"/>
            </t>
        </button>
    </div>

    <!-- Loading skeleton -->
    <t t-if="state.loading">
        <div class="o_sentinella__skeleton">
            <t t-foreach="[1,2,3,4,5]" t-as="i" t-key="i">
                <div class="skel-card"/>
            </t>
        </div>
        <div class="o_sentinella__skeleton">
            <t t-foreach="[1,2]" t-as="i" t-key="i">
                <div class="skel-card" style="height:220px; grid-column: span 2"/>
            </t>
        </div>
    </t>

    <!-- TAB 1: SEMAFORO FINANCIERO -->
    <t t-if="!state.loading &amp;&amp; state.activeTab === 'kpis'">

        <div class="o_sentinella__kpi-grid" t-if="state.data &amp;&amp; state.data.kpis">
            <t t-foreach="state.data.kpis" t-as="kpi" t-key="kpi.key">
                <div t-attf-class="o_sentinella__kpi-card {{ stateClass(kpi.state) }}">
                    <div class="kpi-label" t-esc="kpi.label"/>
                    <div class="kpi-value" t-esc="kpiDisplay(kpi)"/>
                    <div class="kpi-state" t-esc="stateLabel(kpi.state)"/>
                </div>
            </t>
        </div>

        <div class="o_sentinella__charts">
            <div class="o_sentinella__panel">
                <div class="panel-title">Tendencia Altman Z'</div>
                <div class="panel-sub">Evolucion del score de riesgo. Zona gris: 1.23-2.9</div>
                <div class="o_sentinella__chart-container">
                    <canvas t-ref="altmanChart"/>
                </div>
            </div>
            <div class="o_sentinella__panel" t-if="state.data">
                <div class="panel-title">Resumen Actual</div>
                <div class="panel-sub">Balances al <t t-esc="state.data.meta.date"/></div>
                <table style="width:100%;font-size:13px;border-collapse:collapse;">
                    <tr style="border-bottom:1px solid #eee;">
                        <td style="padding:6px 0;color:#5b6874;">Caja efectiva</td>
                        <td style="padding:6px 0;text-align:right;font-weight:700;"
                            t-esc="getKpiMoney('cash')"/>
                    </tr>
                    <tr style="border-bottom:1px solid #eee;">
                        <td style="padding:6px 0;color:#5b6874;">Cuentas por Cobrar</td>
                        <td style="padding:6px 0;text-align:right;font-weight:700;"
                            t-esc="getKpiMoney('ar')"/>
                    </tr>
                    <tr style="border-bottom:1px solid #eee;">
                        <td style="padding:6px 0;color:#5b6874;">Ventas LTM</td>
                        <td style="padding:6px 0;text-align:right;font-weight:700;"
                            t-esc="getKpiMoney('revenue')"/>
                    </tr>
                </table>
            </div>
        </div>

    </t>

    <!-- TAB 2: ANALISIS DE COSTOS -->
    <t t-if="!state.loading &amp;&amp; state.activeTab === 'costs'">
        <t t-if="state.data &amp;&amp; state.data.costs &amp;&amp; state.data.costs.period_label">

            <div class="o_sentinella__cost-metrics">
                <div class="o_sentinella__cost-metric">
                    <div class="cm-label">Ventas</div>
                    <div class="cm-value" t-esc="formatMoney(state.data.costs.total_revenue)"/>
                    <div t-attf-class="cm-change {{ state.data.costs.revenue_change_pct >= 0 ? 'up' : 'down' }}">
                        <t t-if="state.data.costs.revenue_change_pct >= 0">+</t>
                        <t t-esc="formatNum(Math.abs(state.data.costs.revenue_change_pct), 1)"/>%
                    </div>
                </div>
                <div class="o_sentinella__cost-metric">
                    <div class="cm-label">Margen Bruto</div>
                    <div class="cm-value" t-esc="formatNum(state.data.costs.gross_margin_pct, 1) + '%'"/>
                </div>
                <div class="o_sentinella__cost-metric">
                    <div class="cm-label">EBITDA %</div>
                    <div class="cm-value" t-esc="formatNum(state.data.costs.ebitda_pct, 1) + '%'"/>
                </div>
                <div class="o_sentinella__cost-metric">
                    <div class="cm-label">OPEX / Ventas</div>
                    <div class="cm-value" t-esc="formatNum(state.data.costs.opex_pct, 1) + '%'"/>
                </div>
            </div>

            <div class="o_sentinella__charts">
                <div class="o_sentinella__panel">
                    <div class="panel-title">Top Gastos - Actual vs Anterior</div>
                    <div class="panel-sub">Periodo: <t t-esc="state.data.costs.period_label"/></div>
                    <div class="o_sentinella__chart-container">
                        <canvas t-ref="barChart"/>
                    </div>
                </div>
                <div class="o_sentinella__panel">
                    <div class="panel-title">Distribucion de Gastos</div>
                    <div class="panel-sub">Por cuenta - periodo actual</div>
                    <div class="o_sentinella__chart-container">
                        <canvas t-ref="pieChart"/>
                    </div>
                </div>
            </div>

            <div class="o_sentinella__panel">
                <div class="panel-title">Detalle por Cuenta</div>
                <div class="panel-sub">Anomalias: crecimiento &gt;20% vs periodo anterior</div>
                <table class="o_sentinella__cost-table">
                    <thead>
                        <tr>
                            <th>Cuenta</th>
                            <th>Tipo</th>
                            <th style="text-align:right">Actual</th>
                            <th style="text-align:right">Anterior</th>
                            <th style="text-align:right">Var%</th>
                            <th style="text-align:right">% Ventas</th>
                            <th>Estado</th>
                        </tr>
                    </thead>
                    <tbody>
                        <t t-foreach="state.data.costs.lines" t-as="line" t-key="line_index">
                            <tr t-attf-class="{{ line.state !== 'normal' ? 'is-' + line.state : '' }}">
                                <td t-esc="line.account"/>
                                <td>
                                    <span t-attf-class="badge-cat {{ line.category }}"
                                          t-esc="line.category.toUpperCase()"/>
                                </td>
                                <td style="text-align:right;font-weight:600;"
                                    t-esc="formatMoney(line.current)"/>
                                <td style="text-align:right;color:#5b6874;"
                                    t-esc="formatMoney(line.prev)"/>
                                <td style="text-align:right;">
                                    <span t-attf-class="{{ line.change_pct > 0 ? 'change-positive' : 'change-negative' }}">
                                        <t t-if="line.change_pct > 0">+</t>
                                        <t t-esc="formatNum(line.change_pct, 1)"/>%
                                    </span>
                                </td>
                                <td style="text-align:right;" t-esc="formatNum(line.pct_revenue, 1) + '%'"/>
                                <td>
                                    <t t-if="line.state === 'anomalia'">Anomalia</t>
                                    <t t-elif="line.state === 'exceso'">Exceso</t>
                                    <t t-else="">OK</t>
                                </td>
                            </tr>
                        </t>
                    </tbody>
                </table>
            </div>

        </t>
        <t t-else="">
            <div class="o_sentinella__panel" style="text-align:center;padding:48px;">
                <p style="color:#5b6874;font-size:16px;">No hay analisis de costos disponible aun.</p>
                <button class="sl-btn sl-btn-primary" t-on-click="computeNow">
                    Calcular Ahora
                </button>
            </div>
        </t>
    </t>

    <!-- TAB 3: RECOMENDACIONES -->
    <t t-if="!state.loading &amp;&amp; state.activeTab === 'recommendations'">
        <t t-if="state.data &amp;&amp; state.data.recommendations &amp;&amp; state.data.recommendations.length">
            <div class="o_sentinella__rec-grid">
                <t t-foreach="state.data.recommendations" t-as="rec" t-key="rec.id">
                    <div class="o_sentinella__rec-card">
                        <div class="rec-header">
                            <div class="rec-icon-title">
                                <span class="rec-title" t-esc="rec.title"/>
                            </div>
                            <span t-attf-class="rec-priority p{{ rec.priority }}">
                                <t t-if="rec.priority === '1'">Alta</t>
                                <t t-elif="rec.priority === '2'">Media</t>
                                <t t-else="">Baja</t>
                            </span>
                        </div>
                        <div class="rec-body">
                            <span t-esc="rec.category_label" style="font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.06em;"/>
                        </div>
                        <div class="rec-footer">
                            <span class="rec-impact" t-if="rec.impact > 0">
                                Impacto: <t t-esc="formatMoney(rec.impact)"/>
                            </span>
                            <span t-else=""/>
                            <div class="rec-actions">
                                <t t-if="rec.state === 'abierta'">
                                    <button class="sl-btn sl-btn-outline sl-btn-sm"
                                            t-on-click="() => this.updateRecommendation(rec.id, 'en_proceso')">
                                        En proceso
                                    </button>
                                    <button class="sl-btn sl-btn-outline sl-btn-sm"
                                            t-on-click="() => this.updateRecommendation(rec.id, 'cerrada')">
                                        Cerrar
                                    </button>
                                </t>
                                <t t-elif="rec.state === 'en_proceso'">
                                    <button class="sl-btn sl-btn-primary sl-btn-sm"
                                            t-on-click="() => this.updateRecommendation(rec.id, 'cerrada')">
                                        Completar
                                    </button>
                                </t>
                            </div>
                        </div>
                    </div>
                </t>
            </div>
        </t>
        <t t-else="">
            <div class="o_sentinella__panel" style="text-align:center;padding:48px;">
                <p style="color:#5b6874;font-size:16px;">No hay recomendaciones activas.</p>
            </div>
        </t>
    </t>

</div>
`;

export class SentinellaDashboard extends Component {
    static template = TEMPLATE;
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
            activeTab: "kpis",
            chartNonce: 0,
            animatedKpis: {},
            selectedCompanyId: null,
        });

        onWillStart(async () => {
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
            this.notification.add(_t("Computo completado."), { type: "success" });
        } catch (e) {
            this.notification.add(e.message || _t("Error en computo."), { type: "danger" });
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
        return this.state.data && this.state.data.meta && this.state.data.meta.currency_id;
    }

    formatMoney(value) {
        return formatMonetary(value || 0, { currencyId: this.currencyId });
    }

    formatNum(value, decimals) {
        return formatFloat(value || 0, { digits: [0, decimals !== undefined ? decimals : 1] });
    }

    getKpiMoney(key) {
        if (!this.state.data || !this.state.data.kpis) return "—";
        const kpi = this.state.data.kpis.find(function(k) { return k.key === key; });
        return kpi ? this.formatMoney(kpi.value || 0) : "—";
    }

    kpiDisplay(kpi) {
        if (!kpi) return "";
        const animated = this.state.animatedKpis[kpi.key];
        const val = animated !== undefined ? animated : kpi.value;
        if (kpi.unit === "x") return this.formatNum(val, 2) + "x";
        if (kpi.unit === "dias") return this.formatNum(val, 0) + " dias";
        if (kpi.unit === "") return this.formatNum(val, 2);
        return this.formatNum(val, 1);
    }

    stateClass(state) {
        return state === "rojo" ? "is-red" : state === "amarillo" ? "is-yellow" : "is-green";
    }

    stateLabel(state) {
        return state === "rojo" ? "Critico" : state === "amarillo" ? "Precaucion" : "Saludable";
    }

    // ── KPI animation ───────────────────────────────────────────────────────

    animateKpis() {
        const kpis = this.state.data && this.state.data.kpis ? this.state.data.kpis : [];
        const targets = {};
        const starts = {};
        kpis.forEach(function(k) { targets[k.key] = k.value; starts[k.key] = 0; });
        const duration = 700;
        const startTime = performance.now();
        const self = this;

        const ease = function(t) {
            return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        };

        const step = function(now) {
            const progress = Math.min((now - startTime) / duration, 1);
            const eased = ease(progress);
            const animated = {};
            Object.keys(targets).forEach(function(key) {
                animated[key] = starts[key] + (targets[key] - starts[key]) * eased;
            });
            self.state.animatedKpis = animated;
            if (progress < 1) {
                self.animationFrame = requestAnimationFrame(step);
            }
        };
        this.animationFrame = requestAnimationFrame(step);
    }

    // ── Chart rendering ─────────────────────────────────────────────────────

    destroyCharts() {
        const instances = this.chartInstances;
        Object.keys(instances).forEach(function(k) {
            try { instances[k].destroy(); } catch (e) {}
        });
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

    _chartOpts(extra) {
        const base = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 } } },
                tooltip: { mode: "index", intersect: false },
            },
        };
        if (extra) {
            Object.assign(base, extra);
        }
        return base;
    }

    _renderAltmanChart() {
        const el = this.altmanChartRef.el;
        if (!el || !this.state.data || !this.state.data.altman_history || !this.state.data.altman_history.length) return;
        const history = this.state.data.altman_history;
        const labels = history.map(function(h) { return h.date; });
        const data = history.map(function(h) { return h.z; });

        this.chartInstances.altman = new Chart(el, {
            type: "line",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Altman Z'",
                        data: data,
                        borderColor: "#176B87",
                        backgroundColor: "rgba(23,107,135,0.10)",
                        tension: 0.32,
                        fill: true,
                        pointRadius: 4,
                    },
                    {
                        label: "Zona Gris (2.9)",
                        data: labels.map(function() { return 2.9; }),
                        borderColor: "#F4B860",
                        borderDash: [6, 4],
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                    },
                    {
                        label: "Distress (1.23)",
                        data: labels.map(function() { return 1.23; }),
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
        if (!el || !this.state.data || !this.state.data.costs) return;
        const lines = this.state.data.costs.lines || [];
        const slice = lines.slice(0, 8);
        const currentData = slice.map(function(l) { return l.current; });
        const prevData = slice.map(function(l) { return l.prev; });
        const lineLabels = slice.map(function(l) {
            return l.account.length > 20 ? l.account.substring(0, 20) + "..." : l.account;
        });

        this.chartInstances.bar = new Chart(el, {
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
                            callback: function(v) {
                                if (v >= 1000000) return (v / 1000000).toFixed(1) + "M";
                                if (v >= 1000) return (v / 1000).toFixed(0) + "K";
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
        const costs = this.state.data && this.state.data.costs;
        if (!el || !costs || !costs.pie_labels || !costs.pie_labels.length) return;

        this.chartInstances.pie = new Chart(el, {
            type: "pie",
            data: {
                labels: costs.pie_labels,
                datasets: [{
                    data: costs.pie_values,
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
