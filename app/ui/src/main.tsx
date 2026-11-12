import { FluentProvider, webLightTheme } from '@fluentui/react-components'
import ReactDOM from 'react-dom/client'
import { BrowserRouter as Router } from 'react-router-dom'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <Router>
    <FluentProvider theme={webLightTheme}>
      <App />
    </FluentProvider>
  </Router>
)
