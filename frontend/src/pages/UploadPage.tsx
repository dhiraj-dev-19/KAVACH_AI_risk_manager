import React, { useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { uploadCsv, uploadPdf, uploadScreenshot } from '../services/api';
import type { UploadResponse } from '../services/api';
import {
  UploadCloud,
  FileSpreadsheet,
  FileText,
  Image as ImageIcon,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Lock,
  ArrowRight,
  FileCheck,
  X,
  History,
} from 'lucide-react';


type UploadTab = 'csv' | 'pdf' | 'screenshot';

interface TabConfig {
  id: UploadTab;
  label: string;
  subtitle: string;
  icon: React.ElementType;
  accept: string;
  allowedExtensions: string[];
  maxSizeMB: number;
}

const TABS: TabConfig[] = [
  {
    id: 'csv',
    label: 'CSV Upload',
    subtitle: 'Bulk scoring of raw transaction records',
    icon: FileSpreadsheet,
    accept: '.csv',
    allowedExtensions: ['.csv'],
    maxSizeMB: 50,
  },
  {
    id: 'pdf',
    label: 'PDF Bank Statement',
    subtitle: 'Extract & score text-based bank statements',
    icon: FileText,
    accept: '.pdf',
    allowedExtensions: ['.pdf'],
    maxSizeMB: 20,
  },
  {
    id: 'screenshot',
    label: 'Payment Screenshot',
    subtitle: 'Extract single transaction via Gemini vision',
    icon: ImageIcon,
    accept: '.png,.jpg,.jpeg,.webp,.gif',
    allowedExtensions: ['.png', '.jpg', '.jpeg', '.webp', '.gif'],
    maxSizeMB: 10,
  },
];

export const UploadPage: React.FC = () => {
  const { token } = useAuth();

  const [activeTab, setActiveTab] = useState<UploadTab>('csv');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorDetails, setErrorDetails] = useState<any | null>(null);
  const [successResponse, setSuccessResponse] = useState<UploadResponse | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const currentTab = TABS.find((t) => t.id === activeTab)!;

  const handleTabChange = (tab: UploadTab) => {
    if (loading) return;
    setActiveTab(tab);
    setSelectedFile(null);
    setErrorDetails(null);
    setSuccessResponse(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleFileChange = (file: File | null) => {
    setErrorDetails(null);
    setSuccessResponse(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }

    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!currentTab.allowedExtensions.includes(ext)) {
      setErrorDetails({
        message: `Invalid file extension "${ext}". Please select a ${currentTab.accept} file.`,
      });
      setSelectedFile(null);
      return;
    }

    setSelectedFile(file);
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileChange(e.dataTransfer.files[0]);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile || !token || loading) return;

    setLoading(true);
    setErrorDetails(null);
    setSuccessResponse(null);

    try {
      let res: UploadResponse;
      if (activeTab === 'csv') {
        res = await uploadCsv(token, selectedFile);
      } else if (activeTab === 'pdf') {
        res = await uploadPdf(token, selectedFile);
      } else {
        res = await uploadScreenshot(token, selectedFile);
      }
      setSuccessResponse(res);
    } catch (err: any) {
      const responseData = err?.response?.data;
      const detail = responseData?.detail || responseData;

      if (detail) {
        setErrorDetails(detail);
      } else if (err?.message) {
        setErrorDetails({ message: err.message });
      } else {
        setErrorDetails({ message: 'An unexpected network error occurred while uploading.' });
      }
    } finally {
      setLoading(false);
    }
  };

  // Auth Gate check
  if (!token) {
    return (
      <div className="max-w-4xl mx-auto py-12 px-4">
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-10 text-center space-y-6 shadow-xl backdrop-blur">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center mx-auto shadow-lg shadow-blue-500/20">
            <Lock className="w-8 h-8 text-white" />
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-bold text-white tracking-tight">Sign in to Upload Transactions</h2>
            <p className="text-sm text-slate-400 max-w-md mx-auto">
              You must be authenticated to upload CSV files, PDF bank statements, or payment screenshots for risk scoring.
            </p>
          </div>
          <div className="pt-2">
            <Link
              to="/login"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm shadow-lg shadow-blue-600/20 transition"
            >
              <span>Sign In to Continue</span>
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  };

  const renderError = () => {
    if (!errorDetails) return null;

    // String detail
    if (typeof errorDetails === 'string') {
      return (
        <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-800/50 text-rose-300 text-sm flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div>{errorDetails}</div>
        </div>
      );
    }

    // Object detail with column mismatch
    if (errorDetails.error === 'column_mismatch' || errorDetails.missing_columns) {
      return (
        <div className="p-5 rounded-xl bg-rose-950/60 border border-rose-800/50 text-rose-300 text-sm space-y-3">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-rose-200">Column Mismatch Detected</div>
              <p className="text-xs text-rose-300/80 mt-0.5">
                {errorDetails.message || 'The CSV is missing required columns expected by the scoring pipeline.'}
              </p>
            </div>
          </div>

          {errorDetails.missing_columns && (
            <div className="bg-rose-950/80 border border-rose-900/60 rounded-lg p-3 space-y-1 text-xs">
              <div className="font-semibold text-rose-200">Missing Columns ({errorDetails.missing_columns.length}):</div>
              <div className="flex flex-wrap gap-1.5 pt-1">
                {errorDetails.missing_columns.map((col: string) => (
                  <span key={col} className="px-2 py-0.5 rounded bg-rose-900/60 border border-rose-700/50 text-rose-200 font-mono">
                    {col}
                  </span>
                ))}
              </div>
            </div>
          )}

          {errorDetails.detected_columns && (
            <div className="text-xs text-slate-400 pt-1">
              <span className="text-slate-300 font-medium">Detected Columns:</span> {errorDetails.detected_columns.join(', ')}
            </div>
          )}
        </div>
      );
    }

    // Scanned PDF error or extraction failed error
    if (errorDetails.error === 'scanned_pdf_not_supported' || errorDetails.error === 'extraction_failed') {
      return (
        <div className="p-4 rounded-xl bg-amber-950/60 border border-amber-800/50 text-amber-300 text-sm flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-semibold text-amber-200">
              {errorDetails.error === 'scanned_pdf_not_supported'
                ? 'Scanned PDF Not Supported'
                : 'Screenshot Extraction Failed'}
            </div>
            <p className="text-xs text-amber-300/80">
              {errorDetails.message || 'Could not parse text or fields from the uploaded document.'}
            </p>
          </div>
        </div>
      );
    }

    // Generic fallback for any object message
    return (
      <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-800/50 text-rose-300 text-sm flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
        <div>{errorDetails.message || errorDetails.detail || JSON.stringify(errorDetails)}</div>
      </div>
    );
  };

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight flex items-center gap-3">
            <UploadCloud className="w-7 h-7 text-blue-400" />
            <span>Upload Transactions</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Score transaction records, bank statements, or payment screenshots through the AI Risk Manager.
          </p>
        </div>
        <Link
          to="/batch-history"
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 transition self-start md:self-auto"
        >
          <History className="w-4 h-4 text-slate-400" />
          <span>View Batch History</span>
        </Link>
      </div>

      {/* Tabs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => handleTabChange(tab.id)}
              disabled={loading}
              className={`flex flex-col p-4 rounded-xl text-left border transition-all ${
                isActive
                  ? 'bg-blue-950/40 border-blue-500/60 shadow-lg shadow-blue-500/10'
                  : 'bg-slate-900/60 border-slate-800/80 hover:bg-slate-800/50 text-slate-400'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <div
                  className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                    isActive ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  <Icon className="w-5 h-5" />
                </div>
                {isActive && <div className="w-2 h-2 rounded-full bg-blue-400" />}
              </div>
              <span className={`text-sm font-semibold ${isActive ? 'text-white' : 'text-slate-200'}`}>
                {tab.label}
              </span>
              <span className="text-[11px] text-slate-400 mt-0.5">{tab.subtitle}</span>
            </button>
          );
        })}
      </div>

      {/* Main Upload Box */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 sm:p-8 space-y-6 shadow-xl backdrop-blur">
        {successResponse ? (
          /* Success View */
          <div className="py-8 text-center space-y-6">
            <div className="w-16 h-16 rounded-2xl bg-emerald-950/80 border border-emerald-800/60 flex items-center justify-center mx-auto text-emerald-400 shadow-lg shadow-emerald-500/10">
              <CheckCircle2 className="w-9 h-9" />
            </div>
            <div className="space-y-2">
              <h2 className="text-xl font-bold text-white">Upload & Scoring Complete!</h2>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                Processed <span className="font-semibold text-emerald-400">{successResponse.rows_processed}</span> transaction(s) successfully.
              </p>
            </div>

            <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 max-w-md mx-auto text-left space-y-2 text-xs font-mono text-slate-300">
              <div className="flex justify-between">
                <span className="text-slate-500">Batch ID:</span>
                <span className="text-blue-400 font-semibold">{successResponse.batch_id || successResponse.upload_batch_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Rows Processed:</span>
                <span className="text-slate-200">{successResponse.rows_processed}</span>
              </div>
              {typeof successResponse.rows_errored === 'number' && (
                <div className="flex justify-between">
                  <span className="text-slate-500">Rows Errored:</span>
                  <span className={successResponse.rows_errored > 0 ? 'text-rose-400' : 'text-slate-200'}>
                    {successResponse.rows_errored}
                  </span>
                </div>
              )}
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
              <Link
                to="/batch-history"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm shadow-lg shadow-blue-600/20 transition"
              >
                <History className="w-4 h-4" />
                <span>View in Batch History</span>
              </Link>
              <button
                onClick={() => {
                  setSuccessResponse(null);
                  setSelectedFile(null);
                }}
                className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium border border-slate-700 transition"
              >
                Upload Another File
              </button>
            </div>
          </div>
        ) : (
          /* Upload Form */
          <form onSubmit={handleSubmit} className="space-y-6">
            {renderError()}

            {/* Hidden File Input */}
            <input
              ref={fileInputRef}
              type="file"
              accept={currentTab.accept}
              onChange={(e) => handleFileChange(e.target.files ? e.target.files[0] : null)}
              className="hidden"
            />

            {/* Dropzone */}
            {!selectedFile ? (
              <div
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all ${
                  dragActive
                    ? 'border-blue-500 bg-blue-950/30 scale-[1.01]'
                    : 'border-slate-800 hover:border-slate-700 bg-slate-950/50 hover:bg-slate-950/80'
                }`}
              >
                <div className="w-14 h-14 rounded-2xl bg-slate-800/80 border border-slate-700/60 flex items-center justify-center mx-auto text-slate-300 mb-4 shadow-sm">
                  <UploadCloud className="w-7 h-7 text-blue-400" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-slate-200">
                    Click to browse or drop your {currentTab.id.toUpperCase()} file here
                  </p>
                  <p className="text-xs text-slate-500">
                    Accepts {currentTab.accept} files (Max {currentTab.maxSizeMB}MB)
                  </p>
                </div>
              </div>
            ) : (
              /* File Selected Preview Box */
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3.5 min-w-0">
                  <div className="w-10 h-10 rounded-lg bg-blue-950/80 border border-blue-800/60 flex items-center justify-center text-blue-400 shrink-0">
                    <FileCheck className="w-5 h-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-slate-200 truncate">{selectedFile.name}</div>
                    <div className="text-xs text-slate-500">{formatFileSize(selectedFile.size)}</div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedFile(null)}
                  disabled={loading}
                  className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
                  title="Remove selected file"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            )}

            {/* Explicit Upload Action Button */}
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="submit"
                disabled={!selectedFile || loading}
                className="w-full sm:w-auto flex items-center justify-center gap-2 py-3 px-6 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm shadow-lg shadow-blue-600/20 disabled:opacity-40 transition"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Processing {currentTab.label}...</span>
                  </>
                ) : (
                  <>
                    <span>Upload {currentTab.label}</span>
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
