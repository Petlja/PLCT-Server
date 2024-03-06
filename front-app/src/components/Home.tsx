// import { useContext } from 'react'
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
//import { AppContext } from "../AppContext";

class CourseItem {
    title: string;
    course_key: string;

    constructor(title: string, course_key: string) {
        this.title = title;
        this.course_key = course_key;
    }
}

export function Home() {
    // const context = useContext(AppContext);
    const [courses, setCourses] = useState<CourseItem[]>([]);

    useEffect(() => {
        async function loadCourses() {
            const r = await fetch(
                "../api/courses",
                {
                    method: 'GET',
                    headers: {
                        "Accept": "application/json"
                    }
                });
            setCourses(await r.json())
        }
        loadCourses();
    }, []);
    return (
        <div>
            <h2>Kursevi</h2>
            <ul>
                {courses.map((c, i) => <li key={i}><a href={"../course/" + c.course_key+"/index.html"}>{c.title}</a></li>)}
            </ul>
        </div>
    );
}

