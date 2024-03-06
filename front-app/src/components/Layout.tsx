import { PropsWithChildren } from 'react';
import { Container } from 'reactstrap';
import { NavMenu } from './NavMenu';

export function Layout(props: PropsWithChildren) {
    return (
        <div>
            <NavMenu />
            <Container tag="main">
                {props.children}
            </Container>
        </div>
    );
}

