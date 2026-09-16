import axios from 'axios';
import type {
  AuthResponse,
  BatchDetailResponse,
  BatchListResponse,
  ScoredTransaction,
  StreamResponse,
  ThresholdAnalysisResponse,
} from '../types';

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

const client = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
});

// ── Auth endpoints ─────────────────────────────────────────────────────────────

export const loginUser = async (credentials: { email: string; password: string }): Promise<AuthResponse> => {
  const res = await client.post<AuthResponse>('/auth/login', credentials);
  return res.data;
};

export const signupUser = async (credentials: { email: string; password: string }): Promise<AuthResponse> => {
  const res = await client.post<AuthResponse>('/auth/signup', credentials);
  return res.data;
};


// ── Unauthenticated endpoints (existing, unchanged) ───────────────────────────

export const fetchLiveTransactions = async (limit: number = 50): Promise<StreamResponse> => {
  try {
    const res = await client.get<StreamResponse>(`/transactions/live?limit=${limit}`);
    return res.data;
  } catch (err) {
    console.warn('[API] Live stream fetch failed, returning fallback seed data:', err);
    return getFallbackStreamData();
  }
};

export const fetchTransactionDetail = async (txId: string): Promise<ScoredTransaction> => {
  try {
    const res = await client.get<ScoredTransaction>(`/transactions/${txId}`);
    return res.data;
  } catch (err) {
    console.warn('[API] Transaction detail fetch failed, returning fallback detail:', err);
    return getFallbackTransactionDetail(txId);
  }
};

export const fetchThresholdCurve = async (): Promise<ThresholdAnalysisResponse> => {
  try {
    const res = await client.get<ThresholdAnalysisResponse>('/threshold-curve');
    return res.data;
  } catch (err) {
    console.warn('[API] Threshold curve fetch failed, returning fallback curve:', err);
    return getFallbackThresholdCurve();
  }
};

export const triggerSeedBatch = async (): Promise<void> => {
  try {
    await client.post('/simulation/seed');
  } catch (err) {
    console.warn('[API] Seed simulation trigger failed:', err);
  }
};

// ── Authenticated helpers ─────────────────────────────────────────────────────

function authHeaders(token: string) {
  return { Authorization: `Bearer ${token}` };
}

// ── Phase 4: Batch history endpoints ─────────────────────────────────────────

/**
 * Fetch the list of upload batches belonging to the authenticated user.
 * Returns batches sorted by created_at descending (most recent first).
 */
export const fetchBatches = async (token: string): Promise<BatchListResponse> => {
  const res = await client.get<BatchListResponse>('/transactions/batches', {
    headers: authHeaders(token),
  });
  return res.data;
};

/**
 * Fetch all transactions + scores + personal_context for a single batch.
 * Throws on 403 (batch belongs to another user) or 404.
 */
export const fetchBatchDetail = async (
  token: string,
  batchId: string,
): Promise<BatchDetailResponse> => {
  const res = await client.get<BatchDetailResponse>(`/transactions/batches/${batchId}`, {
    headers: authHeaders(token),
  });
  return res.data;
};

export interface UploadResponse {
  batch_id?: string;
  upload_batch_id?: string;
  rows_processed: number;
  rows_errored?: number;
  results_summary?: any[];
  errors?: any[];
}

/**
 * Upload a CSV file and score all rows.
 * Returns the batch summary including personal_context per row.
 */
export const uploadCsv = async (token: string, file: File): Promise<UploadResponse> => {
  const form = new FormData();
  form.append('file', file);
  const res = await client.post<UploadResponse>('/transactions/upload-csv', form, {
    headers: {
      ...authHeaders(token),
      'Content-Type': 'multipart/form-data',
    },
  });
  return res.data;
};

/**
 * Upload a text-based PDF bank statement.
 */
export const uploadPdf = async (token: string, file: File): Promise<UploadResponse> => {
  const form = new FormData();
  form.append('file', file);
  const res = await client.post<UploadResponse>('/transactions/upload-pdf', form, {
    headers: {
      ...authHeaders(token),
      'Content-Type': 'multipart/form-data',
    },
    timeout: 60000,
  });
  return res.data;
};

/**
 * Upload a payment screenshot image (PNG, JPEG, WebP).
 */
export const uploadScreenshot = async (token: string, file: File): Promise<UploadResponse> => {
  const form = new FormData();
  form.append('file', file);
  const res = await client.post<UploadResponse>('/transactions/upload-screenshot', form, {
    headers: {
      ...authHeaders(token),
      'Content-Type': 'multipart/form-data',
    },
    timeout: 60000,
  });
  return res.data;
};


// ── Fallback Data for offline / initial development resilience ────────────────
function getFallbackStreamData(): StreamResponse {
  return {
    count: 5,
    transactions: [
      {
        transaction_id: 'TXN-881901',
        timestamp: new Date().toISOString(),
        merchant: 'fraud_Vandervort_Tech',
        merchant_category: 'shopping_net',
        amount: 1850.0,
        card_num: '4532_8899_0011',
        device_id: 'DEV_ATO_991',
        risk_score: 0.88,
        risk_band: 'very_high',
        action: 'auto_decline',
        cohort_context: {
          merchant: 'fraud_Vandervort_Tech',
          merchant_category: 'shopping_net',
          historical_mean_amount: 65.0,
          amount_ratio_vs_baseline: 28.46,
          baseline_zscore: 4.8,
        },
        explanation: 'Flagged (AUTO_DECLINE): Transaction of $1,850.00 is 28.5x above historical baseline ($65.00), exhibiting an extreme risk score of 0.88 with 4.8 baseline z-score deviation.',
        estimated_fp_cost: 2035.0,
        estimated_fraud_caught: 1850.0,
      },
      {
        transaction_id: 'TXN-881902',
        timestamp: new Date(Date.now() - 4000).toISOString(),
        merchant: 'fraud_Cruickshank_Apparel',
        merchant_category: 'shopping_net',
        amount: 620.0,
        card_num: '4532_1122_3344',
        device_id: 'DEV_VEL_44',
        risk_score: 0.72,
        risk_band: 'high',
        action: 'hold_for_verification',
        cohort_context: {
          merchant: 'fraud_Cruickshank_Apparel',
          merchant_category: 'shopping_net',
          historical_mean_amount: 85.0,
          amount_ratio_vs_baseline: 7.29,
          baseline_zscore: 3.1,
        },
        explanation: 'Flagged (HOLD_FOR_VERIFICATION): Rapid velocity of $620.00 purchase detected (7.3x merchant baseline). Requires secondary step-up verification.',
        estimated_fp_cost: 682.0,
        estimated_fraud_caught: 620.0,
      },
      {
        transaction_id: 'TXN-881903',
        timestamp: new Date(Date.now() - 8000).toISOString(),
        merchant: 'fraud_Baumbach_Stores',
        merchant_category: 'grocery_pos',
        amount: 42.5,
        card_num: '4532_5566_7788',
        device_id: 'DEV_NOR_12',
        risk_score: 0.04,
        risk_band: 'low',
        action: 'allow',
        cohort_context: {
          merchant: 'fraud_Baumbach_Stores',
          merchant_category: 'grocery_pos',
          historical_mean_amount: 48.0,
          amount_ratio_vs_baseline: 0.89,
          baseline_zscore: -0.2,
        },
        explanation: 'Transaction cleared standard automated risk boundary checks.',
        estimated_fp_cost: 0,
        estimated_fraud_caught: 0,
      },
    ],
  };
}

function getFallbackTransactionDetail(txId: string): ScoredTransaction {
  return {
    transaction_id: txId,
    timestamp: new Date().toISOString(),
    merchant: 'fraud_Vandervort_Tech',
    merchant_category: 'shopping_net',
    amount: 1450.0,
    card_num: '4532_9999_1111',
    device_id: 'DEV_ATO_99',
    risk_score: 0.82,
    risk_band: 'high',
    action: 'hold_for_verification',
    cohort_context: {
      merchant: 'fraud_Vandervort_Tech',
      merchant_category: 'shopping_net',
      historical_mean_amount: 65.0,
      amount_ratio_vs_baseline: 22.3,
      baseline_zscore: 4.1,
    },
    top_features: {
      amount_baseline_zscore: 4.1,
      distinct_cards_per_device_24h: 3.0,
      merchant_amt_sum_1h: 2150.0,
      decline_rate_1h: 0.33,
    },
    explanation: 'Flagged (HOLD_FOR_VERIFICATION): Transaction of $1,450.00 is 22.3x above baseline ($65.00), with 3 distinct cards used on the same device within 24 hours.',
    threshold_used: 0.35,
    estimated_fp_cost: 1595.0,
    estimated_fraud_caught: 1450.0,
  };
}

function getFallbackThresholdCurve(): ThresholdAnalysisResponse {
  return {
    optimal_threshold: 0.35,
    recommended_bands: {
      low: { max: 0.35, action: 'allow' },
      medium: { min: 0.35, max: 0.60, action: 'flag_for_review' },
      high: { min: 0.60, max: 0.85, action: 'hold_for_verification' },
      very_high: { min: 0.85, max: 1.0, action: 'auto_decline' },
    },
    threshold_curve: [
      { threshold: 0.1, precision: 0.55, recall: 0.99, f1_score: 0.71, estimated_fp_cost: 6500.0, estimated_fraud_caught: 19800.0 },
      { threshold: 0.2, precision: 0.72, recall: 0.96, f1_score: 0.82, estimated_fp_cost: 3200.0, estimated_fraud_caught: 19200.0 },
      { threshold: 0.35, precision: 0.89, recall: 0.92, f1_score: 0.9, estimated_fp_cost: 1150.0, estimated_fraud_caught: 18400.0 },
      { threshold: 0.5, precision: 0.94, recall: 0.84, f1_score: 0.89, estimated_fp_cost: 450.0, estimated_fraud_caught: 16800.0 },
      { threshold: 0.65, precision: 0.97, recall: 0.71, f1_score: 0.82, estimated_fp_cost: 180.0, estimated_fraud_caught: 14200.0 },
      { threshold: 0.8, precision: 0.99, recall: 0.52, f1_score: 0.68, estimated_fp_cost: 50.0, estimated_fraud_caught: 10400.0 },
    ],
  };
}
