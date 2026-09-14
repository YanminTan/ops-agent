import React, { useState, useEffect } from 'react'
import { listSops, startDiagnosis, getDiagnosis, approveInterrupt } from '../api'

export default function AlertAnalysis() {
  const [sops, setSops] = useState([])
  const [selectedSop, setSelectedSop] = useState('')
  const [alertContext, setAlertContext] = useState({
    source: 'prometheus',
    level: 'critical',
    message: '',
    timestamp: new Date().toISOString(),
    service: '',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    loadSops()
  }, [])

  const loadSops = async () => {
    try {
      const res = await listSops()
      setSops(res.data.sops || [])
      if (res.data.sops?.length > 0) {
        setSelectedSop(res.data.sops[0].sop_id)
      }
    } catch (err) {
      setError('加载 SOP 列表失败')
    }
  }

  const handleStart = async () => {
    if (!selectedSop) {
      setError('请选择 SOP')
      return
    }

    setLoading(true)
    setError('')
    setResult(null)

    try {
      const res = await startDiagnosis(selectedSop, alertContext)
      setResult(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || '启动诊断失败')
    } finally {
      setLoading(false)
    }
  }

  const handleApprove = async (approved) => {
    if (!result?.thread_id) return

    setLoading(true)
    try {
      const res = await approveInterrupt(result.thread_id, approved, '审批通过')
      setResult(res.data)
    } catch (err) {
      setError('审批失败')
    } finally {
      setLoading(false)
    }
  }

  const handleRefresh = async () => {
    if (!result?.thread_id) return

    try {
      const res = await getDiagnosis(result.thread_id)
      setResult(res.data)
    } catch (err) {
      setError('刷新状态失败')
    }
  }

  return (
    <div className="page">
      <h2 className="page-title">🚨 告警分析</h2>

      <div className="card">
        <h3 className="card-title">告警信息</h3>
        
        <div className="form-group">
          <label>选择 SOP</label>
          <select 
            value={selectedSop} 
            onChange={(e) => setSelectedSop(e.target.value)}
          >
            <option value="">-- 请选择 --</option>
            {sops.map(sop => (
              <option key={sop.sop_id} value={sop.sop_id}>
                {sop.name} (v{sop.version})
              </option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label>告警来源</label>
          <input 
            type="text"
            value={alertContext.source}
            onChange={(e) => setAlertContext({...alertContext, source: e.target.value})}
          />
        </div>

        <div className="form-group">
          <label>告警级别</label>
          <select 
            value={alertContext.level}
            onChange={(e) => setAlertContext({...alertContext, level: e.target.value})}
          >
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </div>

        <div className="form-group">
          <label>告警消息</label>
          <textarea
            value={alertContext.message}
            onChange={(e) => setAlertContext({...alertContext, message: e.target.value})}
            placeholder="输入告警详情..."
          />
        </div>

        <div className="form-group">
          <label>影响服务</label>
          <input
            type="text"
            value={alertContext.service}
            onChange={(e) => setAlertContext({...alertContext, service: e.target.value})}
            placeholder="例如: order-service"
          />
        </div>

        <button 
          className="btn btn-primary"
          onClick={handleStart}
          disabled={loading}
        >
          {loading ? '分析中...' : '开始诊断'}
        </button>

        {error && <p style={{color: 'red', marginTop: '12px'}}>{error}</p>}
      </div>

      {result && (
        <div className="card">
          <h3 className="card-title">
            诊断结果 
            <span className={`status-badge status-${result.status}`}>
              {result.status === 'completed' ? '已完成' : 
               result.status === 'waiting_approval' ? '待审批' :
               result.status === 'error' ? '错误' : '运行中'}
            </span>
          </h3>

          {result.pending_interrupt && (
            <div className="approval-dialog">
              <h3>⚠️ 需要人工审批</h3>
              <p>{result.pending_interrupt.message}</p>
              <div className="approval-actions">
                <button 
                  className="btn btn-success"
                  onClick={() => handleApprove(true)}
                  disabled={loading}
                >
                  批准
                </button>
                <button 
                  className="btn btn-danger"
                  onClick={() => handleApprove(false)}
                  disabled={loading}
                >
                  拒绝
                </button>
              </div>
            </div>
          )}

          {result.final_report && (
            <div className="report">
              <h3 className="card-title">📋 诊断报告</h3>
              <div dangerouslySetInnerHTML={{
                __html: result.final_report
                  .replace(/^# (.+)$/gm, '<h1>$1</h1>')
                  .replace(/^## (.+)$/gm, '<h2>$1</h2>')
                  .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                  .replace(/^- (.+)$/gm, '<li>$1</li>')
                  .replace(/\n/g, '<br/>')
              }} />
            </div>
          )}

          {result.execution_log?.length > 0 && (
            <div style={{marginTop: '24px'}}>
              <h3 className="card-title">📝 执行日志</h3>
              <div className="execution-log">
                {result.execution_log.map((log, idx) => (
                  <div key={idx} className={`log-entry ${log.status || ''}`}>
                    <strong>[{log.type}]</strong> {log.step_id}
                    {log.tool && ` → ${log.tool}`}
                    {log.error && <span style={{color: 'red'}}> - {log.error}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <button 
            className="btn btn-primary"
            onClick={handleRefresh}
            style={{marginTop: '16px'}}
          >
            刷新状态
          </button>
        </div>
      )}
    </div>
  )
}
