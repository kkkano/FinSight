import React, { useState } from 'react';
import { X, Mail, CheckCircle, Loader2 } from 'lucide-react';
import axios from 'axios';

interface SubscribeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SubscribeModal: React.FC<SubscribeModalProps> = ({ isOpen, onClose }) => {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  if (!isOpen) return null;

  const handleSubscribe = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;

    setStatus('loading');
    try {
      // 调用后端 API
      await axios.post('http://127.0.0.1:8000/api/subscribe', { email });
      setStatus('success');
      setMessage('订阅成功！请留意您的邮箱。');
      setTimeout(() => {
        onClose();
        setStatus('idle');
        setEmail('');
        setMessage('');
      }, 2000);
    } catch (error) {
      setStatus('error');
      setMessage('订阅失败，请稍后重试。');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-fin-panel border border-fin-border rounded-2xl w-full max-w-md p-6 shadow-2xl relative animate-slide-up">
        {/* Close Button */}
        <button 
          onClick={onClose}
          className="absolute top-4 right-4 text-fin-muted hover:text-fin-text transition-colors"
        >
          <X size={20} />
        </button>

        {/* Header */}
        <div className="flex items-center space-x-3 mb-6">
          <div className="p-3 bg-fin-primary/10 rounded-full text-fin-primary">
            <Mail size={24} />
          </div>
          <div>
            <h3 className="text-xl font-bold text-fin-text">订阅每日简报</h3>
            <p className="text-sm text-fin-muted">获取最新市场动态和 AI 分析报告</p>
          </div>
        </div>

        {/* Form */}
        {status === 'success' ? (
          <div className="flex flex-col items-center justify-center py-8 text-trend-up animate-fade-in">
            <CheckCircle size={48} className="mb-4" />
            <p className="text-lg font-medium">{message}</p>
          </div>
        ) : (
          <form onSubmit={handleSubscribe} className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-fin-muted mb-1">
                电子邮箱
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="w-full bg-fin-bg border border-fin-border rounded-lg px-4 py-3 text-fin-text focus:outline-none focus:ring-2 focus:ring-fin-primary/50 transition-all placeholder-fin-muted/50"
                required
              />
            </div>
            
            {status === 'error' && (
              <p className="text-sm text-trend-down">{message}</p>
            )}

            <button
              type="submit"
              disabled={status === 'loading'}
              className="w-full bg-fin-primary hover:bg-blue-600 text-white font-medium py-3 rounded-lg transition-all flex items-center justify-center disabled:opacity-70 disabled:cursor-not-allowed"
            >
              {status === 'loading' ? (
                <>
                  <Loader2 size={18} className="animate-spin mr-2" />
                  处理中...
                </>
              ) : (
                '立即订阅'
              )}
            </button>
          </form>
        )}
        
        <p className="text-xs text-fin-muted text-center mt-6">
          我们尊重您的隐私，随时可以取消订阅。
        </p>
      </div>
    </div>
  );
};

