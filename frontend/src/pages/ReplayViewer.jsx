import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getThreadHistory, replayToCheckpoint } from '../api'

export default function ReplayViewer() {
  const { threadId } = useParams()
  const [history, setHistory] = useState([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (threadId) {
      loadHistory()
    }
  }, [threadId])

  const loadHistory = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await getThreadHistory(threadId)
      setHistory(res.data.history || [])
      setCurrentIndex(0)
    } catch (err) {
      setError('加载历史记录失败')
    } finally {
      setLoading(false)
    }
  }

  const handlePrev = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1)
    }
  }

  const handleNext = () => {
    if (currentIndex < history.length - 1) {
      setCurrentIndex(currentIndex + 1)
    }
  }

  const handleReplay = async (checkpointId) => {
    try {
      await replayToCheckpoint(threadId, checkpointId)
      await loadHistory()
    } catch (err) {
      setError('回放失败')
    }
  }

  const currentSnapshot = history[currentIndex]

  const getStepIcon = (type) => {
    const icons = {
      tool_call: '🔧',
      llm_analysis: '🤖',
      branch: '🔀',
      interrupt: '⏸️',
      report_section: '📝',
      approval: '✅',
    }
    return icons[type] || '⚙️'
  }

  return (
    <div className="page">
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24}}>
        <h2 className="page-title" style={{margin: 0}}>🎬 逐帧回放</h2>
        <Link to="/history" className="btn btn-primary">返回历史</Link>
      </div>

      {loading ? (
        <div className="loading">
          <div className="spinner"></div>
          <p>加载中...</p>
        </div>
      ) : error ? (
        <div className="empty">
          <div className="empty-icon">❌</div>
          <p>{error}</p>
        </div>
      ) : history.length === 0 ? (
        <div className="empty">
          <div className="empty-icon">📭</div>
          <p>暂无历史记录</p>
        </div>
      ) : (
        <>
          {/* 控制面板 */}
          <div className="card">
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
              <button 
                className="btn btn-primary"
                onClick={handlePrev}
                disabled={currentIndex === 0}
              >
                ◀ 上一步
              </button>
              
              <div style={{textAlign: 'center'}}>
                <div style={{fontSize: 18, fontWeight: 600}}>
                  步骤 {currentIndex + 1} / {history.length}
                </div>
                <div style={{fontSize: 12, color: '#999', marginTop: 4}}>
                  {currentSnapshot?.timestamp && new Date(currentSnapshot.timestamp).toLocaleString('zh-CN')}
                </div>
              </div>
              
              <button 
                className="btn btn-primary"
                onClick={handleNext}
                disabled={currentIndex === history.length - 1}
              >
                下一步 ▶
              </button>
            </div>

            {/* 进度条 */}
            <div style={{
              marginTop: 16,
              height: 4,
              background: '#f0f0f0',
              borderRadius: 2,
              overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${((currentIndex + 1) / history.length) * 100}%`,
                background: '#1890ff',
                transition: 'width 0.3s',
              }} />
            </div>
          </div>

          {/* 当前快照 */}
          {currentSnapshot && (
            <>
              {/* 状态信息 */}
              <div className="card">
                <h3 className="card-title">
                  {getStepIcon(currentSnapshot.values?.current_step)} 
                  {' '}
                  当前状态
                </h3>
                
                <div style={{marginBottom: 12}}>
                  <strong>当前步骤:</strong> {currentSnapshot.values?.current_step || 'N/A'}
                </div>

                {currentSnapshot.values?.error && (
                  <div style={{
                    background: '#fff2f0',
                    border: '1px solid #ffccc7',
                    borderRadius: 4,
                    padding: 12,
                    color: '#ff4d4f',
                    marginBottom: 12,
                  }}>
                    <strong>错误:</strong> {currentSnapshot.values.error}
                  </div>
                )}

                {currentSnapshot.values?.pending_interrupt && (
                  <div style={{
                    background: '#fff7e6',
                    border: '1px solid #ffd591',
                    borderRadius: 4,
                    padding: 12,
                    marginBottom: 12,
                  }}>
                    <strong>⏸️ 等待审批:</strong>
                    <div style={{marginTop: 8}}>
                      {currentSnapshot.values.pending_interrupt.message}
                    </div>
                  </div>
                )}
              </div>

              {/* 收集的事实 */}
              {Object.keys(currentSnapshot.values?.collected_facts || {}).length > 0 && (
                <div className="card">
                  <h3 className="card-title">📊 收集的事实</h3>
                  <pre style={{
                    background: '#f5f5f5',
                    padding: 12,
                    borderRadius: 4,
                    fontSize: 13,
                    overflow: 'auto',
                    maxHeight: 300,
                  }}>
                    {JSON.stringify(currentSnapshot.values.collected_facts, null, 2)}
                  </pre>
                </div>
              )}

              {/* 步骤结果 */}
              {Object.keys(currentSnapshot.values?.step_results || {}).length > 0 && (
                <div className="card">
                  <h3 className="card-title">🔍 步骤结果</h3>
                  <pre style={{
                    background: '#f5f5f5',
                    padding: 12,
                    borderRadius: 4,
                    fontSize: 13,
                    overflow: 'auto',
                    maxHeight: 300,
                  }}>
                    {JSON.stringify(currentSnapshot.values.step_results, null, 2)}
                  </pre>
                </div>
              )}

              {/* 报告段落 */}
              {Object.keys(currentSnapshot.values?.report_sections || {}).length > 0 && (
                <div className="card">
                  <h3 className="card-title">📋 报告段落</h3>
                  {Object.entries(currentSnapshot.values.report_sections).map(([key, content]) => (
                    <div key={key} style={{marginBottom: 16}}>
                      <div 
                        className="report"
                        dangerouslySetInnerHTML={{
                          __html: content
                            .replace(/^## (.+)$/gm, '<h3>$1</h3>')
                            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                            .replace(/^- (.+)$/gm, '<li>$1</li>')
                            .replace(/\n/g, '<br/>')
                        }}
                      />
                    </div>
                  ))}
                </div>
              )}

              {/* 执行日志 */}
              {currentSnapshot.values?.execution_log?.length > 0 && (
                <div className="card">
                  <h3 className="card-title">📝 执行日志</h3>
                  <div className="execution-log">
                    {currentSnapshot.values.execution_log.map((log, idx) => (
                      <div key={idx} className={`log-entry ${log.status || ''}`}>
                        {getStepIcon(log.type)} <strong>[{log.type}]</strong> {log.step_id}
                        {log.tool && ` → ${log.tool}`}
                        {log.error && <span style={{color: 'red'}}> - {log.error}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* 时间线导航 */}
          <div className="card">
            <h3 className="card-title">🕒 时间线</h3>
            <div className="timeline">
              {history.map((snapshot, idx) => (
                <div 
                  key={idx}
                  className={`timeline-item ${idx === currentIndex ? 'current' : ''}`}
                  style={{cursor: 'pointer'}}
                  onClick={() => setCurrentIndex(idx)}
                >
                  <div className="timeline-time">
                    {snapshot.timestamp && new Date(snapshot.timestamp).toLocaleString('zh-CN')}
                  </div>
                  <div className="timeline-content">
                    <div style={{fontWeight: 500}}>
                      {getStepIcon(snapshot.values?.current_step)} 
                      {' '}
                      {snapshot.values?.current_step || '初始化'}
                    </div>
                    {snapshot.values?.error && (
                      <div style={{color: '#ff4d4f', fontSize: 12, marginTop: 4}}>
                        错误: {snapshot.values.error}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
