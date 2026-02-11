import { useState /*, useContext */} from 'react';
import { Collapse, Navbar, NavbarBrand, NavbarToggler, NavItem, NavLink } from 'reactstrap';
import { Link } from 'react-router-dom';
import './NavMenu.css';
// import { AppContext } from "../AppContext";

export function NavMenu() {
    const [isCollapsed, setCollapsed] = useState(false)
    // const context = useContext(AppContext);

    function toggleCollapsed() {
        setCollapsed(!isCollapsed);
    }

    return (
        <header>
            <Navbar className="navbar-expand-sm navbar-toggleable-sm ng-white border-bottom box-shadow mb-3" container light>
                <NavbarBrand tag={Link} to={"/"}>PLCT Server</NavbarBrand>
                <NavbarToggler onClick={toggleCollapsed} className="mr-2" />
                <Collapse className="d-sm-inline-flex flex-sm-row-reverse" isOpen={isCollapsed} navbar>
                    <ul className="navbar-nav flex-grow">
                        <NavItem>
                            <NavLink tag={Link} className="text-dark" to={"/"}>Kursevi</NavLink>
                        </NavItem>
                        <NavItem>
                            <NavLink tag={Link} className="text-dark" to={"/chat"}>AI Asistent</NavLink>
                        </NavItem>
                    </ul>
                </Collapse>
            </Navbar>
        </header>
    );
}
