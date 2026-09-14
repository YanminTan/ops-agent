import React, { useState, useEffect } from 'react'
import { listThreads, getDiagnosis } from '../api'
import { Link } from 'react-router-dom'

export default function HistoryBrowser() {
  const [threads, setThreads] = useState([])
  const [selectedThread, setSelectedThread] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadThreads()
  }, [])

  const loadThreads = async () => {
    setLoading(true)
    try {
      const res = await listThreads()
      setThreads(res.data.threads || [])
    } catch (err) {
      console.error('加载历史失败:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleViewDetail = async (threadId) => {
    try {
      const res = await getDiagnosis(threadId)
      setSelectedThread(res.data)
    } catch (err) {
      console.error('加载详情失败:', err)
    }
  }

  const getStatusBadge = (status) => {
    const statusMap = {
      completed: { text: '已完成', class: 'status-completed' },
      waiting_approval: { text: '待审批', class: 'status-waiting' },
      running: { text: '运行中', class: 'status-running' },
      error: { text: '错误', class: 'status-error' },
    }
    const info = statusMap[status] || { text: status, class: '' }
    return <span className={`status-badge ${info.class}`}>{info.text}</span>
  }

  return (
    <div className="page">
      <h2 className="page-title">📚 历史浏览</h2>

      <div className="card">
        <h3 className="card-title">诊断记录</h3>
        
        {loading ? (
          <div className="loading">
            <div className="spinner"></div>
            <p>加载中...</p>
          </div>
        ) : threads.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">📭</div>
            <p>暂无诊断记录</p>
          </div>
        ) : (
          <div>
            {threads.map(thread => (
              <div key={thread.thread_id} className="list-item">
                <div>
                  <div style={{fontWeight: 500, marginBottom: 4}}>
                    {thread.sop_id}
                  </div>
                  <div style={{fontSize: 12, color: '#999'}}>
                    Thread: {thread.thread_id.substring(0, 8)}...
                  </div>
                  <div style={{fontSize: 12, color: '#999'}}>
                    {new Date(thread.created_at).toLocaleString('zh-CN')}
                  </div>
                </div>
                <div style={{display: 'flex', gap: 12, alignItems: 'center'}}>
                  {getStatusBadge(thread.status)}
                  <button 
                    className="btn btn-primary"
                    onClick={() => handleViewDetail(thread.thread_id)}
                  >
                    查看详情
                  </button>
                  <Link 
                    to={`/replay/${thread.thread_id}`}
                    className="btn btn-primary"
                  >
                    逐帧回放
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {selectedThread && (
        <div className="card">
          <h3 className="card-title">诊断详情</h3>
          
          <div style={{marginBottom: 16}}>
            <strong>Thread ID:</strong> {selectedThread.thread_id}
          </div>
          
          <div style={{marginBottom: 16}}>
            <strong>SOP:</strong> {selectedThread.sop_id}
          </div>
          
          <div style={{marginBottom: 16}}>
            <strong>状态:</strong> {getStatusBadge(selectedThread.status)}
          </div>

          <div style={{marginBottom: 16}}>
            <strong>当前步骤:</strong> {selectedThread.current_step || 'N/A'}
          </div>

          {selectedThread.alert_context && (
            <div style={{marginBottom: 16}}>
              <strong>告警上下文:</strong>
              <pre style={{
                background: '#f5f5f5',
                padding: 12,
                borderRadius: 4,
                marginTop: 8,
                fontSize: 13,
                overflow: 'auto',
              }}>
                {JSON.stringify(selectedThread.alert_context, null, 2)}
              </pre>
            </div>
          )}

          {selectedThread.final_report && (
            <div style={{marginBottom: 16}}>
              <strong>诊断报告:</strong>
              <div className="report" style={{marginTop: 8}}>
                <div dangerouslySetInnerHTML={{
                  __html: selectedThread.final_report
                    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
                    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                    .replace(/^- (.+)$/gm, '<li>$1</li>')
                    .replace(/\n/g, '<br/>')
                }} />
              </div>
            </div>
          )}

          {selectedThread.execution_log?.length > 0 && (
            <div>
              <strong>执行日志:</strong>
              <div className="execution-log" style={{marginTop: 8}}>
                {selectedThread.execution_log.map((log, idx) => (
                  <div key={idx} className={`log-entry ${log.status || ''}`}>
                    <strong>[{log.type}]</strong> {log.step_id}
                    {log.tool && ` → ${log.tool}`}
                    {log.error && <span style={{color: 'red'}}> - {log.error}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
