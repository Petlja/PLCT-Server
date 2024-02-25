// import { useContext } from 'react'
import { Link } from 'react-router-dom';
//import { AppContext } from "../AppContext";

export function Home() {
    // const context = useContext(AppContext);
    return (
        <div>
            <h1>PLCT Server - dodatne mogućnosti</h1>

            <p>Trenutno možete testirati kako radi:</p>
            <ul>
                <li><Link to={"../chat"}>AI chat</Link> - odgovori na pitanja o prograniranju u Pajtonu</li>
            </ul>
        </div>
    );
}

