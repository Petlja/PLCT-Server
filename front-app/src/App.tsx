import { useState } from 'react';
import { useCookies } from 'react-cookie';
import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Home } from "./components/Home";
import { Chat } from "./components/Chat"
import './custom.css';
import { AppContextType, AppContext } from "./AppContext"



export default function App() {

    const params = new URLSearchParams(window.location.search);
    const ak = params.get("ak");
    const [cookie, setCookie] = useCookies(["BackendApiKey"]);

    if (ak) {
        setCookie("BackendApiKey", ak);
    }

    const [context] = useState<AppContextType>({ accessKey: ak ?? cookie["BackendApiKey"] })

    return (
        <AppContext.Provider value={context}>
            <Layout>
                <Routes>
                    <Route key={0} path="/" element={<Home />} />
                    <Route key={1} path="/chat" element={<Chat />} />
                </Routes>
            </Layout>
        </AppContext.Provider>
    );
}
