import { Component } from 'react'

// round33, блок C.1: авария (белый экран после ReferenceError в MapView.jsx,
// docs/round33-reboot-incident.md, блок A2) показала, что необработанное
// исключение при рендере размонтирует всё дерево React и оставляет
// #root пустым — без всякого сообщения. Граница ошибок не предотвращает
// сам баг, но не даёт ЛЮБОМУ будущему необработанному исключению рендера
// снова превращаться в тишину: пользователь видит сообщение и кнопку
// повтора вместо белого экрана.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', height: '100vh', width: '100vw',
          fontFamily: 'sans-serif', textAlign: 'center', padding: 24,
        }}>
          <h2>Не удалось отобразить витрину</h2>
          <p style={{ color: '#666', maxWidth: 480 }}>
            Произошла ошибка при загрузке страницы. Попробуйте обновить —
            если это повторяется, сообщите администратору.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: 16, padding: '10px 20px', fontSize: 16,
              cursor: 'pointer', borderRadius: 6, border: '1px solid #ccc',
            }}
          >
            Обновить страницу
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
