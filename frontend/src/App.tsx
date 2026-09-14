import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { Navbar } from './components/Navbar';
import { LiveFeed } from './pages/LiveFeed';
import { CostCurve } from './pages/CostCurve';
import { TransactionDetail } from './pages/TransactionDetail';
import { Settings } from './pages/Settings';
import { BatchHistory } from './pages/BatchHistory';
import { LoginPage } from './pages/LoginPage';
import { SignupPage } from './pages/SignupPage';
import { UploadPage } from './pages/UploadPage';

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <Router>
        <div className="min-h-screen bg-slate-950 text-slate-100 font-sans antialiased selection:bg-blue-600 selection:text-white">
          <Navbar />
          <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <Routes>
              <Route path="/" element={<LiveFeed />} />
              <Route path="/login" element={<LoginPage />} />
              <Route path="/signup" element={<SignupPage />} />
              <Route path="/upload" element={<UploadPage />} />
              <Route path="/cost-curve" element={<CostCurve />} />
              <Route path="/transactions/:id" element={<TransactionDetail />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/batch-history" element={<BatchHistory />} />
            </Routes>
          </main>
        </div>
      </Router>
    </AuthProvider>
  );
};

export default App;
