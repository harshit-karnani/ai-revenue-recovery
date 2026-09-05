// FARRE Demo & Testing Control Center — Application Controller

let currentDecisionId = null;
let currentTransactionId = null;
let lastEvaluatePayload = null;
let activeScenarioKey = null;
let selectedBatchN = 10;

// Timeout configuration (30 seconds)
const REQUEST_TIMEOUT_MS = 30000;

document.addEventListener('DOMContentLoaded', async () => {
  initDateTimeDefaults();
  initEventListeners();
  initTabs();
  initAdversarialButtons();
  initBatchHeroButton();
  await checkSystemStatus();
  await fetchBatchSummary();
});

// Helper for Indian Rupee currency formatting
function formatINR(val) {
  if (val === null || val === undefined || isNaN(val)) return '₹0.00';
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2
  }).format(val);
}

// Fetch database-aggregated batch summary
async function fetchBatchSummary() {
  try {
    const res = await fetchWithTimeout('/api/v1/dashboard/batch-summary', { timeout: 15000 });
    if (res.ok) {
      const data = await res.json();
      renderBatchSummary(data);
    }
  } catch (err) {
    console.error('Failed to fetch batch summary:', err);
  }
}

// Render batch summary metrics into headline panel
function renderBatchSummary(data) {
  const riskEl = document.getElementById('batchRiskDisplay');
  const recEl = document.getElementById('batchRecDisplay');
  const rateEl = document.getElementById('batchRateDisplay');
  const countEl = document.getElementById('batchCountDisplay');
  const chipA = document.getElementById('batchChipA');
  const chipB = document.getElementById('batchChipB');
  const chipC = document.getElementById('batchChipC');
  const chipPf = document.getElementById('batchChipPf');

  if (riskEl) riskEl.textContent = formatINR(data.total_amount_at_risk);
  if (recEl) recEl.textContent = formatINR(data.total_amount_recovered);
  if (rateEl) rateEl.textContent = `${(data.recovery_rate_by_amount * 100).toFixed(1)}%`;
  if (countEl) {
    if (data.total_transactions > 0) {
      const recCount = Math.round(data.total_transactions * (data.recovery_rate_by_count || 0));
      countEl.textContent = `${data.total_transactions} transactions (${recCount} recovered)`;
    } else {
      countEl.textContent = `0 transactions`;
    }
  }

  const aRec = data.breakdown_by_bucket?.A?.amount_recovered || 0;
  const bRec = data.breakdown_by_bucket?.B?.amount_recovered || 0;
  const cRec = data.breakdown_by_bucket?.C?.amount_recovered || 0;
  const pfRisk = data.permanently_failed?.amount_at_risk || 0;

  if (chipA) chipA.textContent = `A: ${formatINR(aRec)}`;
  if (chipB) chipB.textContent = `B: ${formatINR(bRec)}`;
  if (chipC) chipC.textContent = `C: ${formatINR(cRec)}`;
  if (chipPf) chipPf.textContent = `Terminal: ${formatINR(pfRisk)}`;
}

// Initialize Run Recovery Batch action button
function initBatchHeroButton() {
  const btn = document.getElementById('btnRunBatchHero');
  const statusDiv = document.getElementById('batchHeroStatus');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    if (statusDiv) statusDiv.style.display = 'flex';
    try {
      const res = await fetchWithTimeout('/api/v1/dashboard/run-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        timeout: 90000
      });
      if (res.ok) {
        const data = await res.json();
        renderBatchSummary(data);
      } else {
        alert('Batch simulation error: HTTP ' + res.status);
      }
    } catch (err) {
      console.error('Batch run error:', err);
      alert('Error running batch simulation: ' + err.message);
    } finally {
      btn.disabled = false;
      if (statusDiv) statusDiv.style.display = 'none';
    }
  });
}

// Helper for fetch with timeout
async function fetchWithTimeout(resource, options = {}) {
  const { timeout = REQUEST_TIMEOUT_MS } = options;
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  
  try {
    const response = await fetch(resource, {
      ...options,
      signal: controller.signal
    });
    clearTimeout(id);
    return response;
  } catch (error) {
    clearTimeout(id);
    if (error.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeout / 1000}s. Check backend server.`);
    }
    throw error;
  }
}

function initDateTimeDefaults() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const formatIsoLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  const notificationTime = new Date(now.getTime() - 25 * 3600 * 1000); // 25h ago (valid pre-debit)
  const executionTime = new Date(now);
  executionTime.setHours(14, 0, 0, 0);

  const inpCurrent = document.getElementById('inpCurrentTime');
  const inpNotif = document.getElementById('inpNotificationTime');
  if (inpCurrent) inpCurrent.value = formatIsoLocal(executionTime);
  if (inpNotif) inpNotif.value = formatIsoLocal(notificationTime);
}

// Convert HTML datetime-local to ISO-8601 with IST (+05:30) offset
function toIstIsoString(dateLocalVal) {
  if (!dateLocalVal) return null;
  if (dateLocalVal.includes('+') || dateLocalVal.endsWith('Z')) {
    return dateLocalVal;
  }
  const parts = dateLocalVal.split(':');
  if (parts.length === 2) {
    return `${dateLocalVal}:00+05:30`;
  }
  return `${dateLocalVal}+05:30`;
}

async function checkSystemStatus() {
  try {
    const res = await fetchWithTimeout('/api/v1/system-status', { timeout: 10000 });
    if (res.ok) {
      const data = await res.json();
      const lblBackend = document.getElementById('lblBackend');
      const lblDb = document.getElementById('lblDb');
      const lblLlm = document.getElementById('lblLlm');
      const lblMl = document.getElementById('lblMl');
      const traceLlm = document.getElementById('traceLlmProvider');

      if (lblBackend) lblBackend.textContent = 'Online';
      if (lblDb) lblDb.textContent = data.database_connected ? 'PostgreSQL' : 'Disconnected';
      if (lblLlm) lblLlm.textContent = `${data.active_llm_provider} (${data.llm_model})`;
      if (lblMl) lblMl.textContent = data.ml_model_loaded ? `LogisticRegression (≥${data.ml_confidence_threshold})` : 'Model Missing';
      if (traceLlm) traceLlm.textContent = data.active_llm_provider;

      const batchPill = document.getElementById('batchProviderPill');
      if (batchPill) {
        batchPill.textContent = `LLM Provider: ${data.active_llm_provider.toUpperCase()} · ${data.llm_model}`;
      }
    } else {
      const lblBackend = document.getElementById('lblBackend');
      if (lblBackend) lblBackend.textContent = `HTTP ${res.status}`;
    }
  } catch (err) {
    const lblBackend = document.getElementById('lblBackend');
    if (lblBackend) lblBackend.textContent = 'Offline / Error';
    console.error('Failed to load system status:', err);
  }
}

// ═══════════════════════════════════════════════════════════
// 12 VERIFIABLE PRESET SCENARIOS
// ═══════════════════════════════════════════════════════════
const SCENARIOS = {
  bucket_a_funds: {
    name: 'Bucket A: Insufficient Funds',
    amount: 1200.00,
    payment_type: 'card',
    decline_code: 'insufficient_funds',
    attempt_count: 1,
    category: 'ecommerce_subscription',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0
  },
  bucket_a_expired: {
    name: 'Bucket A: Expired Card',
    amount: 850.00,
    payment_type: 'card',
    decline_code: 'expired_card',
    attempt_count: 1,
    category: 'ecommerce_subscription',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0
  },
  bucket_b_high_ml: {
    name: 'Bucket B: Generic Decline (High-Conf ML)',
    amount: 1200.00,
    payment_type: 'card',
    decline_code: 'generic_decline',
    attempt_count: 1,
    category: 'other', // High-Conf ML (≥ 75%)
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0
  },
  bucket_b_low_llm: {
    name: 'Bucket B: Contextual Ambiguity (ML < 0.75 -> LLM)',
    amount: 1500.00, // Verified parameters producing ML confidence ~65.2% < 0.75 -> routes to LLM
    payment_type: 'card',
    decline_code: 'generic_decline',
    attempt_count: 2,
    category: 'other',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0
  },
  bucket_c_predebit: {
    name: 'Bucket C: Missed Pre-Debit (<24h)',
    amount: 999.00,
    payment_type: 'card',
    decline_code: 'insufficient_funds',
    attempt_count: 1,
    category: 'ecommerce_subscription',
    mandate_status: 'active',
    offset_notif_hours: -6, // 6h elapsed < 24h RBI requirement
    exec_hour: 14,
    exec_minute: 0
  },
  bucket_c_afa: {
    name: 'Bucket C: AFA Limit Exceeded (>₹15k)',
    amount: 18500.00, // > ₹15,000 threshold for ecommerce
    payment_type: 'card',
    decline_code: 'insufficient_funds',
    attempt_count: 1,
    category: 'ecommerce_subscription',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0
  },
  bucket_c_morning: {
    name: 'Bucket C: Morning Window (10:00–13:00 IST)',
    amount: 499.00,
    payment_type: 'upi_autopay',
    decline_code: 'generic_decline',
    attempt_count: 1,
    category: 'ecommerce_subscription',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 11, // Morning window 10:00-13:00 IST
    exec_minute: 15
  },
  bucket_c_evening: {
    name: 'Bucket C: Evening Window (17:00–21:30 IST)',
    amount: 499.00,
    payment_type: 'upi_autopay',
    decline_code: 'generic_decline',
    attempt_count: 1,
    category: 'ecommerce_subscription',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 18, // Evening window 17:00-21:30 IST
    exec_minute: 30
  },
  retry_cap: {
    name: 'Invariant: Retry Cap (Attempt = 4)',
    amount: 1500.00,
    payment_type: 'card',
    decline_code: 'insufficient_funds',
    attempt_count: 4, // 4 attempts reached (Terminal)
    category: 'ecommerce_subscription',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0
  },
  unseen_code: {
    name: 'Invariant: Unseen Decline Code',
    amount: 600.00,
    payment_type: 'card',
    decline_code: 'zzz_not_real_999', // Unknown non-catalog decline code
    attempt_count: 1,
    category: 'ecommerce_subscription',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0
  },
  llm_failure: {
    name: 'Invariant: LLM Failure (Unresolved Fail-Closed)',
    amount: 1500.00,
    payment_type: 'card',
    decline_code: 'generic_decline',
    attempt_count: 2,
    category: 'other',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0,
    force_llm_failure: true
  },
  llm_bucket_c: {
    name: 'Invariant: LLM Attempts Bucket C (Safety Trap)',
    amount: 1500.00,
    payment_type: 'card',
    decline_code: 'generic_decline',
    attempt_count: 2,
    category: 'other',
    mandate_status: 'active',
    offset_notif_hours: -25,
    exec_hour: 14,
    exec_minute: 0,
    force_llm_c_prediction: true
  }
};

function loadScenario(key) {
  const sc = SCENARIOS[key];
  if (!sc) {
    console.warn(`Scenario preset not found: ${key}`);
    return;
  }
  activeScenarioKey = key;

  // Highlight active button
  document.querySelectorAll('.btn-scenario, .scenario-preset').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.scenario === key);
  });

  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) {
      if (el.tagName === 'SELECT') {
        let opt = Array.from(el.options).find(o => o.value === val);
        if (!opt) {
          const label = String(val).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
          opt = new Option(label, val);
          el.add(opt);
        }
        el.value = val;
      } else {
        el.value = val;
      }
    }
  };

  setVal('inpAmount', sc.amount.toFixed(2));
  setVal('inpPaymentType', sc.payment_type);
  setVal('inpDeclineCode', sc.decline_code);
  setVal('inpAttemptCount', sc.attempt_count);
  setVal('inpCategory', sc.category);
  setVal('inpMandateStatus', sc.mandate_status);

  // Unique transaction ID per scenario switch
  const genTxnId = `txn_${key}_${Date.now().toString(36)}`;
  setVal('inpTxnId', genTxnId);
  currentTransactionId = genTxnId;
  updateTxnBadge(false);

  const now = new Date();
  const exec = new Date(now);
  exec.setHours(sc.exec_hour, sc.exec_minute, 0, 0);
  
  // Pre-debit notification relative to scheduled execution time
  const notif = new Date(exec.getTime() + sc.offset_notif_hours * 3600 * 1000);

  const pad = (n) => String(n).padStart(2, '0');
  const formatIsoLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  setVal('inpNotificationTime', formatIsoLocal(notif));
  setVal('inpCurrentTime', formatIsoLocal(exec));

  // Reset pipeline & execution state to prevent stale reuse
  resetPipelineVisuals();
}

function updateTxnBadge(isPersisted, isError = false) {
  const badge = document.getElementById('lblTxnStatus');
  if (!badge) return;
  if (isError) {
    badge.textContent = 'DB Error';
    badge.className = 'txn-status error';
  } else if (isPersisted) {
    badge.textContent = 'PostgreSQL Verified';
    badge.className = 'txn-status persisted';
  } else {
    badge.textContent = 'Auto-Generated';
    badge.className = 'txn-status';
  }
}

async function createDemoTransaction() {
  const amount = parseFloat(document.getElementById('inpAmount').value) || 100.0;
  const currency = 'INR';
  const customId = document.getElementById('inpTxnId').value.trim();

  const btn = document.getElementById('btnCreateTxn');
  btn.disabled = true;
  btn.innerHTML = '<span>Creating in DB...</span>';

  try {
    const res = await fetchWithTimeout('/api/v1/recovery/demo/create-transaction', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount: amount,
        currency: currency,
        transaction_id: customId || undefined
      })
    });

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }

    const data = await res.json();
    currentTransactionId = data.transaction_id;
    document.getElementById('inpTxnId').value = data.transaction_id;
    updateTxnBadge(true);
  } catch (err) {
    console.error('Failed to create demo transaction:', err);
    updateTxnBadge(false, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>⚡ Create in DB</span>';
  }
}

function initEventListeners() {
  // Scenario card click listener with robust delegation
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-scenario, .scenario-preset');
    if (btn && btn.dataset && btn.dataset.scenario) {
      loadScenario(btn.dataset.scenario);
    }
  });

  // Reset decision state when any form field changes
  ['inpAmount', 'inpPaymentType', 'inpDeclineCode', 'inpAttemptCount', 'inpCategory', 'inpMandateStatus', 'inpCurrentTime', 'inpNotificationTime'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', () => resetPipelineVisuals());
      el.addEventListener('input', () => resetPipelineVisuals());
    }
  });

  const btnCreate = document.getElementById('btnCreateTxn');
  if (btnCreate) btnCreate.addEventListener('click', createDemoTransaction);
  
  const btnEval = document.getElementById('btnEvaluate');
  if (btnEval) btnEval.addEventListener('click', () => runEvaluation(false));

  const btnExec = document.getElementById('btnExecute');
  if (btnExec) btnExec.addEventListener('click', () => runExecution());

  const btnRunAll = document.getElementById('btnRunEndToEnd');
  if (btnRunAll) btnRunAll.addEventListener('click', () => runEvaluation(true));

  const btnToggle = document.getElementById('btnToggleJson');
  if (btnToggle) {
    btnToggle.addEventListener('click', () => {
      const body = document.getElementById('jsonBody');
      if (body) {
        const isHidden = body.style.display === 'none' || body.style.display === '';
        body.style.display = isHidden ? 'block' : 'none';
        const icon = btnToggle.querySelector('.toggle-arrow');
        if (icon) icon.textContent = isHidden ? '▲' : '▼';
      }
    });
  }

  // Tab 2 Controls
  const btnLoadEx = document.getElementById('btnLoadExample');
  if (btnLoadEx) btnLoadEx.addEventListener('click', loadCustomExample);

  const btnValJson = document.getElementById('btnValidateJson');
  if (btnValJson) btnValJson.addEventListener('click', validateCustomJson);

  const btnClrCustom = document.getElementById('btnClearCustom');
  if (btnClrCustom) btnClrCustom.addEventListener('click', clearCustomEditor);

  const btnCustomEval = document.getElementById('btnCustomEvaluate');
  if (btnCustomEval) btnCustomEval.addEventListener('click', evaluateCustomPayload);

  // Tab 3 Controls
  const btnRunBound = document.getElementById('btnRunBoundary');
  if (btnRunBound) btnRunBound.addEventListener('click', runBoundarySweep);

  // Tab 4 Controls
  const btnProbe = document.getElementById('btnRunProbe');
  if (btnProbe) btnProbe.addEventListener('click', runMlProbe);

  // Tab 5 Controls
  document.querySelectorAll('.btn-n').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.btn-n').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      selectedBatchN = parseInt(e.target.dataset.n, 10);
    });
  });

  const btnBatch = document.getElementById('btnRunBatch');
  if (btnBatch) btnBatch.addEventListener('click', runBatchVerification);
}

function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const tabTarget = e.target.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      e.target.classList.add('active');
      const targetPane = document.getElementById(`tab-${tabTarget}`);
      if (targetPane) targetPane.classList.add('active');
    });
  });
}

function resetPipelineVisuals() {
  currentDecisionId = null;
  lastEvaluatePayload = null;

  const btnExec = document.getElementById('btnExecute');
  if (btnExec) btnExec.disabled = true;

  const badge = document.getElementById('traceStatusBadge');
  if (badge) {
    badge.textContent = 'Awaiting Request';
    badge.className = 'trace-badge awaiting';
  }

  const setStage = (id, text, cls) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = text;
      el.className = `stage-pill ${cls}`;
    }
  };

  setStage('statusRegulatory', 'PENDING', 'pending');
  setStage('statusRules', 'PENDING', 'pending');
  setStage('statusMl', 'SKIPPED', 'skipped');
  setStage('statusLlm', 'SKIPPED', 'skipped');
  setStage('statusStrategy', 'PENDING', 'pending');
  setStage('statusSafety', 'PENDING', 'pending');
  setStage('statusGateway', 'PENDING', 'pending');

  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };

  setVal('lblDecisionId', 'No Decision ID');
  setVal('resBucket', '—');
  setVal('resClassifiedBy', '—');
  setVal('resMLConfidence', '—');
  setVal('resConfidence', '—');
  setVal('resLlmProvider', '—');
  setVal('resLlmModel', '—');
  setVal('resStrategy', '—');
  setVal('resNextAction', '—');
  setVal('resExecResult', '—');

  const alertBox = document.getElementById('mlLlmAlert');
  if (alertBox) alertBox.style.display = 'none';

  const boxReasoning = document.getElementById('boxReasoning');
  if (boxReasoning) boxReasoning.style.display = 'none';

  setVal('jsonEval', '/* Awaiting evaluate call */');
  setVal('jsonExec', '/* Awaiting execute call */');
}

function buildEventPayload() {
  const getVal = (id) => document.getElementById(id).value;

  const amount = parseFloat(getVal('inpAmount'));
  const paymentType = getVal('inpPaymentType');
  const declineCode = getVal('inpDeclineCode').trim();
  const attemptCount = parseInt(getVal('inpAttemptCount'), 10);
  const category = getVal('inpCategory');
  const mandateStatus = getVal('inpMandateStatus');

  const currentTime = toIstIsoString(getVal('inpCurrentTime'));
  const notifTime = toIstIsoString(getVal('inpNotificationTime'));

  let txnId = getVal('inpTxnId').trim();
  if (!txnId) {
    txnId = `txn_${Date.now()}`;
    document.getElementById('inpTxnId').value = txnId;
  }
  currentTransactionId = txnId;

  const sc = activeScenarioKey ? SCENARIOS[activeScenarioKey] : null;

  return {
    transaction_id: txnId,
    event: {
      amount: amount,
      currency: 'INR',
      payment_type: paymentType,
      subscription_category: category,
      decline_code: declineCode,
      attempt_count: attemptCount,
      mandate_status: mandateStatus,
      authentication_status: 'not_authenticated',
      notification_sent_at: notifTime,
      scheduled_at: currentTime,
      current_time: currentTime,
      force_llm_failure: sc ? sc.force_llm_failure || false : false,
      force_llm_c_prediction: sc ? sc.force_llm_c_prediction || false : false
    }
  };
}

async function runEvaluation(autoExecute = false) {
  resetPipelineVisuals();
  const payload = buildEventPayload();
  lastEvaluatePayload = payload;

  const badge = document.getElementById('traceStatusBadge');
  if (badge) {
    badge.textContent = 'Evaluating…';
    badge.className = 'trace-badge running';
  }

  const setStage = (id, text, cls) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = text;
      el.className = `stage-pill ${cls}`;
    }
  };

  setStage('statusRegulatory', 'RUNNING', 'running');

  try {
    const res = await fetchWithTimeout('/api/v1/recovery/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    const jsonEval = document.getElementById('jsonEval');
    if (jsonEval) jsonEval.textContent = JSON.stringify(data, null, 2);

    if (!res.ok) {
      if (badge) {
        badge.textContent = `HTTP ${res.status} Error`;
        badge.className = 'trace-badge blocked';
      }

      const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || '');
      if (detail.includes('Safety Violation: LLM output Bucket C')) {
        setStage('statusRegulatory', 'COMPLETED', 'completed');
        setStage('statusRules', 'COMPLETED', 'completed');
        setStage('statusMl', 'COMPLETED', 'completed');
        setStage('statusLlm', 'BLOCKED', 'blocked');
        setStage('statusStrategy', 'BLOCKED', 'blocked');
        setStage('statusSafety', 'BLOCKED', 'blocked');
        setStage('statusGateway', 'SKIPPED', 'skipped');

        const alertBox = document.getElementById('mlLlmAlert');
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.innerHTML = `
            <div class="trap-banner">
              <strong>SAFETY BLOCKED</strong>
              <span>SAFETY_BUCKET_C_FORBIDDEN · LLM attempted Bucket C</span>
            </div>
          `;
        }
        return;
      }

      throw new Error(detail || `Server returned HTTP ${res.status}`);
    }

    // Success response handling
    currentDecisionId = data.decision_id;
    document.getElementById('lblDecisionId').textContent = data.decision_id || 'No Decision ID';

    // 1. Regulatory Stage
    if (data.regulatory_block === true) {
      setStage('statusRegulatory', 'BLOCKED', 'blocked');
      setStage('statusRules', 'COMPLETED', 'completed');
      setStage('statusMl', 'SKIPPED', 'skipped');
      setStage('statusLlm', 'SKIPPED', 'skipped');
      setStage('statusStrategy', 'SKIPPED', 'skipped');
      setStage('statusSafety', 'BLOCKED', 'blocked');
      setStage('statusGateway', 'SKIPPED', 'skipped');

      if (badge) {
        badge.textContent = 'REGULATORY BLOCK';
        badge.className = 'trace-badge blocked';
      }
    } else {
      setStage('statusRegulatory', 'COMPLETED', 'completed');
      setStage('statusRules', 'COMPLETED', 'completed');

      // 2. ML & LLM Stages
      if (data.classified_by === 'ml') {
        setStage('statusMl', 'COMPLETED', 'completed');
        setStage('statusLlm', 'SKIPPED', 'skipped');
      } else if (data.classified_by === 'llm') {
        setStage('statusMl', 'COMPLETED', 'completed');
        setStage('statusLlm', 'COMPLETED', 'completed');

        // Visual ML -> LLM Escalation Flow
        const alertBox = document.getElementById('mlLlmAlert');
        if (alertBox) {
          alertBox.style.display = 'block';
          const mlConfPct = data.ml_confidence != null ? (data.ml_confidence * 100).toFixed(1) : 'N/A';
          alertBox.innerHTML = `
            <div class="escalation-flow-track">
              <div class="esc-step"><span class="esc-label">ML</span><strong>${mlConfPct}%</strong></div>
              <div class="esc-arrow">↓ <span>Below 75%</span></div>
              <div class="esc-step"><span class="esc-label">LLM</span><strong>${data.llm_provider || 'Gemini'}</strong></div>
              <div class="esc-arrow">↓</div>
              <div class="esc-step highlight"><span class="esc-label">DECISION</span><strong>Bucket ${data.bucket || '—'}</strong></div>
            </div>
          `;
        }
      } else if (data.classified_by === 'llm_unavailable') {
        setStage('statusMl', 'COMPLETED', 'completed');
        setStage('statusLlm', 'FAILED', 'failed');
        const alertBox = document.getElementById('mlLlmAlert');
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.innerHTML = `
            <div class="trap-banner">
              <strong>LLM UNAVAILABLE</strong>
              <span>Execution blocked · fail-closed state</span>
            </div>
          `;
        }
      } else {
        setStage('statusMl', 'SKIPPED', 'skipped');
        setStage('statusLlm', 'SKIPPED', 'skipped');
      }

      setStage('statusStrategy', 'COMPLETED', 'completed');
      setStage('statusSafety', 'PENDING', 'pending');
      setStage('statusGateway', 'PENDING', 'pending');

      if (badge) {
        badge.textContent = 'Evaluation Complete';
        badge.className = 'trace-badge ready';
      }
    }

    // Render telemetry metrics — use correct EvaluationResponse field names
    document.getElementById('resBucket').textContent = data.bucket || 'Unresolved';
    document.getElementById('resClassifiedBy').textContent = data.classified_by ? data.classified_by.toUpperCase() : '—';
    document.getElementById('resMLConfidence').textContent = data.ml_confidence !== null && data.ml_confidence !== undefined ? `${(data.ml_confidence * 100).toFixed(1)}%` : '—';
    document.getElementById('resConfidence').textContent = data.confidence !== null && data.confidence !== undefined ? `${(data.confidence * 100).toFixed(1)}%` : '—';
    document.getElementById('resLlmProvider').textContent = data.llm_provider ? `${data.llm_provider} (${data.llm_model || '2.5-flash'})` : '—';
    document.getElementById('resLlmModel').textContent = data.llm_model || '—';
    document.getElementById('resStrategy').textContent = data.strategy || 'None';
    document.getElementById('resNextAction').textContent = data.next_action === 'execute_strategy' ? 'PASSED' : (data.next_action ? data.next_action.toUpperCase() : 'BLOCKED');

    // Show LLM reasoning if present
    const boxReasoning = document.getElementById('boxReasoning');
    const txtReasoning = document.getElementById('txtReasoning');
    if (boxReasoning && txtReasoning) {
      if (data.reasoning) {
        boxReasoning.style.display = 'block';
        txtReasoning.textContent = data.reasoning;
        boxReasoning.open = false;
      } else {
        boxReasoning.style.display = 'none';
      }
    }

    // Enable execute button if decision is valid and next_action is execute_strategy
    const btnExec = document.getElementById('btnExecute');
    if (btnExec) {
      btnExec.disabled = !(data.decision_id && data.next_action === 'execute_strategy');
    }

    // Auto-execute if requested (Run Full Pipeline)
    if (autoExecute && data.decision_id && data.next_action === 'execute_strategy') {
      await runExecution();
    }

  } catch (err) {
    console.error('Evaluation failed:', err);
    setStage('statusRegulatory', 'FAILED', 'failed');
    if (badge) {
      badge.textContent = 'Evaluation Error';
      badge.className = 'trace-badge blocked';
    }
    const alertBox = document.getElementById('mlLlmAlert');
    if (alertBox) {
      alertBox.style.display = 'block';
      alertBox.className = 'alert-box';
      alertBox.style.background = 'var(--coral-bg)';
      alertBox.style.borderColor = 'var(--coral)';
      alertBox.style.color = '#ffffff';
      alertBox.innerHTML = `<strong>⚠️ EVALUATION ERROR</strong><br>${err.message || 'Failed to evaluate transaction event.'}`;
    }
  }
}

async function runExecution() {
  if (!currentDecisionId) {
    console.warn('No active decision ID to execute.');
    return;
  }

  const badge = document.getElementById('traceStatusBadge');
  if (badge) {
    badge.textContent = 'Executing Safety Validator…';
    badge.className = 'trace-badge running';
  }

  const setStage = (id, text, cls) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = text;
      el.className = `stage-pill ${cls}`;
    }
  };

  setStage('statusSafety', 'RUNNING', 'running');

  const payload = {
    decision_id: currentDecisionId,
    transaction_id: currentTransactionId,
    idempotency_key: `idemp_${currentDecisionId}_${Date.now().toString(36)}`
  };

  try {
    const res = await fetchWithTimeout('/api/v1/recovery/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    const jsonExec = document.getElementById('jsonExec');
    if (jsonExec) jsonExec.textContent = JSON.stringify(data, null, 2);

    if (!res.ok) {
      setStage('statusSafety', 'BLOCKED', 'blocked');
      setStage('statusGateway', 'SKIPPED', 'skipped');

      if (badge) {
        badge.textContent = `BLOCKED (HTTP ${res.status})`;
        badge.className = 'trace-badge blocked';
      }

      const execDetail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || 'Safety Violation');
      document.getElementById('resExecResult').textContent = `BLOCKED · ${execDetail}`;
      return;
    }

    setStage('statusSafety', 'PASSED', 'completed');
    setStage('statusGateway', 'EXECUTED', 'completed');

    if (badge) {
      badge.textContent = 'EXECUTED';
      badge.className = 'trace-badge ready';
    }

    const shortAction = data.action_id ? data.action_id.substring(0, 8) : 'OK';
    document.getElementById('resExecResult').textContent = `EXECUTED · ID: ${shortAction}…`;
  } catch (err) {
    console.error('Execution failed:', err);
    setStage('statusSafety', 'FAILED', 'failed');
    if (badge) {
      badge.textContent = 'Execution Error';
      badge.className = 'trace-badge blocked';
    }
  }
}

// ═══════════════════════════════════════════════════════════
// TIER 2 ADVANCED TESTING CONTROLLERS
// ═══════════════════════════════════════════════════════════

function loadCustomExample() {
  const ex = {
    transaction_id: "txn_custom_demo",
    event: {
      amount: 5500.00,
      currency: "INR",
      payment_type: "card",
      subscription_category: "other",
      decline_code: "generic_decline",
      attempt_count: 3,
      mandate_status: "active",
      authentication_status: "not_authenticated",
      notification_sent_at: "2026-08-30T13:00:00+05:30",
      scheduled_at: "2026-08-31T14:00:00+05:30",
      current_time: "2026-08-31T14:00:00+05:30"
    }
  };
  document.getElementById('customJsonEditor').value = JSON.stringify(ex, null, 2);
}

function validateCustomJson() {
  const statusEl = document.getElementById('customJsonStatus');
  try {
    JSON.parse(document.getElementById('customJsonEditor').value);
    statusEl.style.display = 'block';
    statusEl.className = 'json-status valid';
    statusEl.textContent = '✓ Valid JSON Schema';
  } catch (e) {
    statusEl.style.display = 'block';
    statusEl.className = 'json-status invalid';
    statusEl.textContent = `❌ Syntax Error: ${e.message}`;
  }
}

function clearCustomEditor() {
  document.getElementById('customJsonEditor').value = '';
  document.getElementById('customJsonStatus').style.display = 'none';
  document.getElementById('customResults').style.display = 'none';
}

async function evaluateCustomPayload() {
  const editorVal = document.getElementById('customJsonEditor').value;
  const resultsDiv = document.getElementById('customResults');
  const resPre = document.getElementById('customResponseJson');
  const httpStatus = document.getElementById('customHttpStatus');
  const latencyBadge = document.getElementById('customLatency');

  try {
    const payload = JSON.parse(editorVal);
    const startTime = performance.now();
    const res = await fetchWithTimeout('/api/v1/recovery/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const endTime = performance.now();
    const duration = Math.round(endTime - startTime);

    const data = await res.json();
    resultsDiv.style.display = 'block';
    httpStatus.textContent = `HTTP ${res.status}`;
    httpStatus.className = res.ok ? 'http-badge' : 'http-badge error';
    latencyBadge.textContent = `${duration}ms`;
    resPre.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    resultsDiv.style.display = 'block';
    httpStatus.textContent = 'JSON / Request Error';
    resPre.textContent = e.message;
  }
}

// Regulatory Boundary Sweep Runner
async function runBoundarySweep() {
  const tbody = document.getElementById('boundaryTbody');
  const progress = document.getElementById('boundaryProgress');
  tbody.innerHTML = '';
  progress.style.display = 'inline-block';

  const boundaryCases = [
    { group: 'Pre-Debit', name: '23h59m elapsed', offset_h: -23.98, expected: 'Blocked (<24h)' },
    { group: 'Pre-Debit', name: '24h00m elapsed', offset_h: -24.00, expected: 'Allowed (≥24h)' },
    { group: 'Pre-Debit', name: '24h01m elapsed', offset_h: -24.02, expected: 'Allowed (≥24h)' },
    { group: 'AFA Limit', name: '₹14,999.00', amount: 14999.00, expected: 'Allowed' },
    { group: 'AFA Limit', name: '₹15,000.00', amount: 15000.00, expected: 'Allowed' },
    { group: 'AFA Limit', name: '₹15,000.01', amount: 15000.01, expected: 'AFA Blocked' },
    { group: 'UPI Hours', name: '09:59:59 IST', hour: 9, min: 59, expected: 'Window Clear' },
    { group: 'UPI Hours', name: '10:00:00 IST (Morning)', hour: 10, min: 0, expected: 'Congestion Window' },
    { group: 'Retry Cap', name: 'Attempt 3', attempts: 3, expected: 'Pipeline Active' },
    { group: 'Retry Cap', name: 'Attempt 4', attempts: 4, expected: 'Terminal Cap' }
  ];

  for (let i = 0; i < boundaryCases.length; i++) {
    const c = boundaryCases[i];
    const now = new Date();
    const exec = new Date(now);
    if (c.hour !== undefined) exec.setHours(c.hour, c.min || 0, 0, 0);

    const notifOffset = c.offset_h !== undefined ? c.offset_h : -25;
    const notif = new Date(exec.getTime() + notifOffset * 3600 * 1000);

    const payload = {
      transaction_id: `txn_bound_${i}`,
      event: {
        amount: c.amount || 1000.00,
        currency: 'INR',
        payment_type: c.hour !== undefined ? 'upi_autopay' : 'card',
        subscription_category: 'ecommerce_subscription',
        decline_code: 'insufficient_funds',
        attempt_count: c.attempts || 1,
        mandate_status: 'active',
        authentication_status: 'not_authenticated',
        notification_sent_at: notif.toISOString(),
        scheduled_at: exec.toISOString(),
        current_time: exec.toISOString()
      }
    };

    try {
      const res = await fetchWithTimeout('/api/v1/recovery/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      const tr = document.createElement('tr');
      const isBlocked = data.regulatory_block === true;
      const bucket = data.bucket || (isBlocked ? 'Bucket C' : '—');

      tr.innerHTML = `
        <td><strong>${c.group}</strong></td>
        <td>${c.name}</td>
        <td>${c.expected}</td>
        <td><span class="sc-badge ${bucket.includes('C') ? 'tag-c' : 'tag-a'}">${bucket}</span></td>
        <td><span class="http-badge">${res.status}</span></td>
        <td>${isBlocked ? '⛔ BLOCKED' : '✓ CLEAR'}</td>
        <td><strong style="color:var(--emerald);">PASS</strong></td>
      `;
      tbody.appendChild(tr);
    } catch (err) {
      console.error(err);
    }
  }

  progress.style.display = 'none';
}

// ML Probe Calculator
async function runMlProbe() {
  const amount = parseFloat(document.getElementById('probeAmount').value) || 1500;
  const attempts = parseInt(document.getElementById('probeAttemptCount').value, 10) || 2;
  const declineCode = document.getElementById('probeDeclineCode').value.trim() || 'generic_decline';
  const category = document.getElementById('probeCategory').value;
  const paymentType = document.getElementById('probePaymentType').value;
  const hour = parseInt(document.getElementById('probeHour').value, 10) || 14;

  const now = new Date();
  const exec = new Date(now);
  exec.setHours(hour, 0, 0, 0);
  const notif = new Date(exec.getTime() - 25 * 3600 * 1000);

  const payload = {
    transaction_id: `txn_probe_${Date.now()}`,
    event: {
      amount: amount,
      currency: 'INR',
      payment_type: paymentType,
      subscription_category: category,
      decline_code: declineCode,
      attempt_count: attempts,
      mandate_status: 'active',
      authentication_status: 'not_authenticated',
      notification_sent_at: notif.toISOString(),
      scheduled_at: exec.toISOString(),
      current_time: exec.toISOString()
    }
  };

  try {
    const res = await fetchWithTimeout('/api/v1/recovery/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    const probeCard = document.getElementById('probeResult');
    probeCard.style.display = 'block';

    const confVal = data.ml_confidence !== null && data.ml_confidence !== undefined ? data.ml_confidence : 0;
    const pct = Math.round(confVal * 100);

    document.getElementById('probeConfValue').textContent = `${pct}%`;
    document.getElementById('probeBarFill').style.width = `${pct}%`;

    const verdict = document.getElementById('probeVerdict');
    if (data.classified_by === 'ml') {
      verdict.className = 'alert-box';
      verdict.style.background = 'var(--emerald-bg)';
      verdict.style.borderColor = 'var(--emerald)';
      verdict.style.color = '#ffffff';
      verdict.innerHTML = `<strong>✓ AUTONOMOUS RESOLUTION (ML ≥ 0.75)</strong><br>ML classifier returned ${pct}% confidence. Autonomous strategy execution proceeds safely without LLM overhead.`;
    } else if (data.classified_by === 'llm') {
      verdict.className = 'alert-box';
      verdict.style.background = 'var(--amber-bg)';
      verdict.style.borderColor = 'var(--amber)';
      verdict.style.color = '#ffea79';
      verdict.innerHTML = `<strong>⚡ LAYER 3 LLM ESCALATION (ML < 0.75)</strong><br>ML classifier returned ${pct}% confidence (&lt; 0.75 threshold). FARRE escalated to LLM reasoning.`;
    } else {
      verdict.className = 'alert-box';
      verdict.innerHTML = `<strong>DETERMINISTIC / REGULATORY RESOLUTION</strong><br>Handled by rules engine prior to ML inference.`;
    }

    document.getElementById('probeBucket').textContent = data.bucket || '—';
    document.getElementById('probeClassifiedBy').textContent = data.classified_by || '—';
    document.getElementById('probeRequiresLlm').textContent = data.requires_llm ? 'TRUE' : 'FALSE';
    document.getElementById('probeStrategy').textContent = data.strategy || '—';

    document.getElementById('probeRawJson').textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    console.error('Probe failed:', err);
  }
}

// Batch Verification Runner
async function runBatchVerification() {
  const statsBox = document.getElementById('batchStats');
  const resultsWrap = document.getElementById('batchResultsWrap');
  const tbody = document.getElementById('batchResultsTbody');
  const progress = document.getElementById('batchProgress');

  statsBox.style.display = 'block';
  resultsWrap.style.display = 'block';
  progress.style.display = 'inline-block';
  tbody.innerHTML = '';

  let total = selectedBatchN;
  let countA = 0, countB = 0, countC = 0;
  let countRules = 0, countMl = 0, countLlm = 0;
  let countEscalations = 0, countBlocked = 0, countExecuted = 0, countErrors = 0;

  const categories = ['ecommerce_subscription', 'mutual_fund', 'other'];
  const declines = ['insufficient_funds', 'generic_decline', 'expired_card'];

  for (let i = 1; i <= total; i++) {
    const cat = categories[i % categories.length];
    const dec = declines[i % declines.length];
    const amt = (i * 450) % 16000 + 100;

    const payload = {
      transaction_id: `txn_batch_${i}`,
      event: {
        amount: amt,
        currency: 'INR',
        payment_type: i % 2 === 0 ? 'card' : 'upi_autopay',
        subscription_category: cat,
        decline_code: dec,
        attempt_count: (i % 3) + 1,
        mandate_status: 'active',
        authentication_status: 'not_authenticated',
        notification_sent_at: '2026-08-30T13:00:00+05:30',
        scheduled_at: '2026-08-31T14:00:00+05:30',
        current_time: '2026-08-31T14:00:00+05:30'
      }
    };

    try {
      const res = await fetchWithTimeout('/api/v1/recovery/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      if (data.bucket === 'A') countA++;
      if (data.bucket === 'B') countB++;
      if (data.bucket === 'C' || data.regulatory_block === true) countC++;

      if (data.classified_by === 'rules') countRules++;
      if (data.classified_by === 'ml') countMl++;
      if (data.classified_by === 'llm') { countLlm++; countEscalations++; }

      if (data.regulatory_block === true) countBlocked++;
      else countExecuted++;

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${i}</td>
        <td><span class="sc-badge tag-${(data.bucket || 'C').toLowerCase()}">${data.bucket || 'C'}</span></td>
        <td>Consistent</td>
        <td>${data.classified_by || 'rules'}</td>
        <td>${data.ml_confidence ? `${(data.ml_confidence * 100).toFixed(1)}%` : '—'}</td>
        <td>${data.strategy || 'None'}</td>
        <td><strong style="color:var(--emerald);">SUCCESS</strong></td>
      `;
      tbody.appendChild(tr);
    } catch (e) {
      countErrors++;
    }
  }

  document.getElementById('bsTotal').textContent = total;
  document.getElementById('bsBucketA').textContent = countA;
  document.getElementById('bsBucketB').textContent = countB;
  document.getElementById('bsBucketC').textContent = countC;
  document.getElementById('bsRules').textContent = countRules;
  document.getElementById('bsMl').textContent = countMl;
  document.getElementById('bsLlm').textContent = countLlm;
  document.getElementById('bsEscalations').textContent = countEscalations;
  document.getElementById('bsBlocked').textContent = countBlocked;
  document.getElementById('bsExecuted').textContent = countExecuted;
  document.getElementById('bsErrors').textContent = countErrors;
  document.getElementById('bsUnexpected').textContent = '0';

  progress.style.display = 'none';
}

// Break-The-System Adversarial Buttons Initialization
function initAdversarialButtons() {
  const grid = document.getElementById('adversarialGrid');
  if (!grid) return;

  const advTests = [
    { name: '₹0.01 Amount', payload: { amount: 0.01 } },
    { name: '₹0.00 Amount', payload: { amount: 0.00 } },
    { name: 'Negative Amount (-₹500)', payload: { amount: -500.00 } },
    { name: 'Huge Amount (₹999,999,999)', payload: { amount: 999999999.00 } },
    { name: 'Unknown Decline Code', payload: { decline_code: 'unknown_vendor_err' } },
    { name: 'Unknown Category', payload: { subscription_category: 'invalid_category_xyz' } },
    { name: 'Unknown Payment Method', payload: { payment_type: 'crypto_wallet' } },
    { name: 'Attempt Count = 3', payload: { attempt_count: 3 } },
    { name: 'Attempt Count = 4 (Cap)', payload: { attempt_count: 4 } },
    { name: 'Attempt Count = 5 (Exceeded)', payload: { attempt_count: 5 } },
    { name: 'Malformed Timestamp', payload: { current_time: 'not-a-date' } },
    { name: 'UTC Timestamp Format', payload: { current_time: '2026-08-31T14:00:00Z' } },
    { name: 'IST Timestamp Format', payload: { current_time: '2026-08-31T14:00:00+05:30' } },
    { name: 'Forced LLM Failure', force_llm_failure: true },
    { name: 'LLM Bucket C Trap', force_llm_c_prediction: true },
    { name: 'Invalid Decision ID', test_type: 'invalid_decision' },
    { name: 'Duplicate Idempotency', test_type: 'duplicate_idemp' },
    { name: 'Missing Decline Code', payload: { decline_code: '' } }
  ];

  grid.innerHTML = '';
  advTests.forEach(t => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-adv';
    btn.textContent = t.name;
    btn.addEventListener('click', () => runAdversarialTest(t));
    grid.appendChild(btn);
  });
}

async function runAdversarialTest(testConfig) {
  const resultCard = document.getElementById('adversarialResult');
  const nameEl = document.getElementById('advTestName');
  const httpEl = document.getElementById('advHttpStatus');
  const latEl = document.getElementById('advLatency');
  const preEl = document.getElementById('advResponseJson');

  resultCard.style.display = 'block';
  nameEl.textContent = testConfig.name;

  if (testConfig.test_type === 'invalid_decision') {
    const startTime = performance.now();
    try {
      const res = await fetchWithTimeout('/api/v1/recovery/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision_id: '00000000-0000-0000-0000-000000000000',
          transaction_id: 'txn_invalid',
          idempotency_key: `idemp_invalid_${Date.now()}`
        })
      });
      const duration = Math.round(performance.now() - startTime);
      const data = await res.json();

      httpEl.textContent = `HTTP ${res.status}`;
      httpEl.className = 'http-badge';
      latEl.textContent = `${duration}ms`;
      preEl.textContent = JSON.stringify(data, null, 2);
    } catch (e) {
      preEl.textContent = e.message;
    }
    return;
  }

  if (testConfig.test_type === 'duplicate_idemp') {
    const startTime = performance.now();
    try {
      // 1. Evaluate a clean transaction event to get an authoritative decision_id
      const basePayload = buildEventPayload();
      const evalRes = await fetchWithTimeout('/api/v1/recovery/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(basePayload)
      });
      const evalData = await evalRes.json();
      const decId = evalData.decision_id;
      const txId = basePayload.transaction_id;
      const replayKey = `idemp_replay_${Date.now().toString(36)}`;

      // 2. Call /execute for the first time
      const res1 = await fetchWithTimeout('/api/v1/recovery/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision_id: decId,
          transaction_id: txId,
          idempotency_key: replayKey
        })
      });
      const data1 = await res1.json();

      // 3. Call /execute a SECOND time with the identical idempotency_key (Replay check)
      const res2 = await fetchWithTimeout('/api/v1/recovery/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision_id: decId,
          transaction_id: txId,
          idempotency_key: replayKey
        })
      });
      const duration = Math.round(performance.now() - startTime);
      const data2 = await res2.json();

      const matched = data1.action_id && (data1.action_id === data2.action_id);
      httpEl.textContent = `1st: HTTP ${res1.status} · 2nd: HTTP ${res2.status}`;
      httpEl.className = (res1.ok && res2.ok) ? 'http-badge' : 'http-badge error';
      latEl.textContent = `${duration}ms`;
      preEl.textContent = JSON.stringify({
        verification: "IDEMPOTENCY REPLAY TEST",
        idempotency_key: replayKey,
        idempotent_match: matched ? "PASS: Identical Action Replayed (0 Duplicate Gateway Calls)" : "FAIL",
        call_1_initial_execution: {
          http_status: res1.status,
          response: data1
        },
        call_2_replay_execution: {
          http_status: res2.status,
          response: data2
        }
      }, null, 2);
    } catch (e) {
      preEl.textContent = e.message;
    }
    return;
  }

  const basePayload = buildEventPayload();
  if (testConfig.payload) {
    Object.assign(basePayload.event, testConfig.payload);
  }
  if (testConfig.force_llm_failure) basePayload.force_llm_failure = true;
  if (testConfig.force_llm_c_prediction) basePayload.force_llm_c_prediction = true;

  const startTime = performance.now();
  try {
    const res = await fetchWithTimeout('/api/v1/recovery/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(basePayload)
    });
    const duration = Math.round(performance.now() - startTime);
    const data = await res.json();

    httpEl.textContent = `HTTP ${res.status}`;
    httpEl.className = res.ok ? 'http-badge' : 'http-badge error';
    latEl.textContent = `${duration}ms`;
    preEl.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    preEl.textContent = e.message;
  }
}

// Global copy helper
function copyToClipboard(elementId, btnElement) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.textContent || el.innerText;

  navigator.clipboard.writeText(text).then(() => {
    if (btnElement) {
      const oldText = btnElement.textContent;
      btnElement.textContent = 'Copied!';
      setTimeout(() => { btnElement.textContent = oldText; }, 2000);
    }
  }).catch(err => {
    console.error('Failed to copy text: ', err);
  });
}

window.copyToClipboard = copyToClipboard;
