import subprocess
from manim import *

class VectorProjection(Scene):
    def construct(self):
        axis(self)
        # Define vectors v and w
        v = np.array([4, 1, 0])
        w = np.array([2, -1, 0])
        
        # Create vector objects
        vec_v = Arrow(ORIGIN, v, buff=0, color=YELLOW)
        vec_w = Arrow(ORIGIN, w, buff=0, color=PINK)
        
        # Calculate the projection of v onto w
        projection_length = np.dot(v, w) / np.linalg.norm(w)
        proj_w = projection_length * w / np.linalg.norm(w)
        vec_proj_w = Arrow(ORIGIN, proj_w, buff=0, color=GREEN)
        
        # Create labels
        label_v = MathTex(r"\vec{v}", color=YELLOW).next_to(vec_v.get_end(), UP)
        label_w = MathTex(r"\vec{w}", color=PINK).next_to(vec_w.get_end(), DOWN)
        label_proj_w = MathTex(r"\text{Proj}_{\vec{w}} \vec{v}", color=GREEN).next_to(vec_proj_w.get_end(), DOWN)
        
        # Create the grid
        grid = NumberPlane()
        
        # Display objects
        self.play(Create(grid))
        self.play(Create(vec_v), Write(label_v))
        self.play(Create(vec_w), Write(label_w))
        
        # Show the projection
        self.play(Create(vec_proj_w), Write(label_proj_w))
        
        # Show the length of the projection
        length_of_proj = np.dot(v, w) / np.linalg.norm(w)**2
        length_label = MathTex(f"Length = {round(length_of_proj, 2)}").to_edge(UP)
        self.play(Write(length_label))
        
        self.wait(2)

class AngleBetweenLines(Scene):
    def construct(self):
        # Definindo os vetores
        axis(self)
        v_r = np.array([-1, -1, 0])  # Vetor diretor da reta r
        v_s = np.array([3, 6, 0])     # Vetor diretor da reta s

        # Criando os vetores
        vector_r = Arrow(ORIGIN, v_r, color=BLUE)
        vector_s = Arrow(ORIGIN, v_s, color=RED)

        # Adicionando os vetores à cena
        self.add(vector_r, vector_s)

        # Calculando o produto escalar
        dot_product = np.dot(v_r, v_s)

        # Calculando as normas
        norm_r = np.linalg.norm(v_r)
        norm_s = np.linalg.norm(v_s)

        # Calculando o cosseno do ângulo
        cos_theta = dot_product / (norm_r * norm_s)

        # Calculando o ângulo em graus
        theta = np.arccos(cos_theta) * (180 / np.pi)

        # Exibindo o ângulo
        angle_label = MathTex(f"\\theta \\approx {theta:.2f}^\\circ").next_to(vector_r, RIGHT)
        self.add(angle_label)

        # Adicionando o título
        title = Text("Angle Between Lines").to_edge(UP)
        self.add(title)

        # Mostrando a cena
        self.wait(2)

# Para executar, você precisará usar o comando `manim -pql your_file.py AngleBetweenLines`
class SpotlightScene(Scene):
    def construct(self):
        axis(self, 3)
        # Define the spotlight direction and position
        spotlight_direction = np.array([0.5, 0.92, -0.4])
        spotlight_position = np.array([0.0, 1.0, 0.5])
        
        # Create a light cone (represented as a triangle for simplicity)
        cone_base = Circle(radius=2, color=WHITE, fill_opacity=0.5)
        cone_tip = Dot3D(point=spotlight_position, color=YELLOW, radius=0.1)

        # Create a visual representation of the light direction
        light_direction_line = Arrow(
            start=spotlight_position,
            end=spotlight_position + spotlight_direction,
            color=YELLOW,
            buff=0
        )

        # Create a surface to represent the ground
        ground = Square(side_length=4, fill_color=BLUE, fill_opacity=0.5).shift(DOWN)

        # Add elements to the scene
        self.add(ground)
        self.add(cone_base)
        self.add(cone_tip)
        self.add(light_direction_line)

        # Animate the spotlight effect
        self.play(Create(cone_base), Create(cone_tip), Create(light_direction_line))
        self.wait(1)

        # Simulate the spotlight effect by changing the direction
        new_direction = np.array([-0.5, 0.5, -0.4])
        new_light_direction_line = light_direction_line.copy().set_end(spotlight_position + new_direction)

        self.play(Transform(light_direction_line, new_light_direction_line))
        self.wait(1)
class LineAngle(Scene):
    def construct(self):
        axis(self)
        # Definindo os pontos
        point_A = np.array([2, 1, 0])  # Ponto (2, 1)
        point_B = np.array([1, 0, 0])   # Ponto (1, 0)

        # Criando os pontos e as etiquetas
        dot_A = Dot(point_A, color=BLUE)
        dot_B = Dot(point_B, color=RED)
        label_A = MathTex("(2, 1)").next_to(dot_A, UP)
        label_B = MathTex("(1, 0)").next_to(dot_B, DOWN)

        # Criando a linha
        line = Line(point_A, point_A + np.array([1, 1, 0]), color=YELLOW)

        # Adicionando tudo à cena
        self.play(Create(line), Create(dot_A), Create(dot_B), Write(label_A), Write(label_B))
        self.wait(2)

        # Adicionando a equação da reta
        equation = MathTex("y = x - 1").to_edge(UP)
        self.play(Write(equation))
        self.wait(2)
class LineExample(Scene):
    def construct(self):
        axis(self)
        # Criando os pontos A e B
        A = np.array([1, 2, 0])
        B = np.array([3, -1, 0])
        
        # Criando os pontos e as etiquetas
        point_A = Dot(A, color=BLUE)
        point_B = Dot(B, color=RED)
        label_A = MathTex("A(1, 2)").next_to(point_A, UP)
        label_B = MathTex("B(3, -1)").next_to(point_B, DOWN)
        
        # Criando a linha
        line = Line(point_A, point_B, color=YELLOW)
        
        # Adicionando tudo à cena
        self.play(Create(line), Create(point_A), Create(point_B), Write(label_A), Write(label_B))
        self.wait(2)

        # Adicionando a equação da reta
        equation = MathTex("3x + 2y - 7 = 0").to_edge(UP)
        self.play(Write(equation))
        self.wait(2)
class MatrixTransformation(Scene):
    def construct(self):
        axis(self)
        # Define the vector as an array of points
        original_vector = np.array([1, 1, 0])
        transformed_vector = np.array([2, 3, 1])

        # Create the matrix as a MathTex object for display
        matrix_label = MathTex("A = \\begin{pmatrix} 2 & 0 \\\\ 0 & 1 \\end{pmatrix}")
        matrix_label.to_edge(UP)
        
        # Create the vector and transformed vector as Dot objects
        vector = Arrow(ORIGIN, original_vector, buff=0, color=BLUE)
        vector_label = MathTex("\\mathbf{v} = \\begin{pmatrix} 1 \\\\ 1 \\end{pmatrix}")
        vector_label.next_to(matrix_label, DOWN)

        # Display the matrix and the initial vector
        self.play(Write(matrix_label), Write(vector_label), Create(vector))
        self.wait(1)

        # Define the matrix transformation
        def matrix_transform(vector):
            transformation_matrix = np.array([[2, 2], [1, 1]])
            return transformation_matrix @ vector[:2]  # Apply the transformation

        # Transform the vector
        new_vector = Arrow(ORIGIN, transformed_vector, buff=0, color=RED)
        self.play(Transform(vector, new_vector))
        
        # Display the result
        result_label = MathTex("\\mathbf{v'} = \\begin{pmatrix} 2 \\\\ 1 \\end{pmatrix}")
        result_label.next_to(vector_label, DOWN)
        self.play(Write(result_label))
        self.wait(2)

class CartesianMatrixTransformation(Scene):
    def construct(self):
        axes = Axes(
            x_range=(-10, 10),
            y_range=(-10, 10),
            axis_config={"color": BLUE},
        )

        # Create the original vector [2, 4]
        original_vector = Arrow(ORIGIN, [2, 4, 0], color=YELLOW)
        original_label = MathTex(r"\begin{pmatrix} 2 \\ 4 \end{pmatrix}").next_to(original_vector, UP)

        # Create the transformation matrix
        transformation_matrix = Matrix([[-1, -1], [-1, -1]], left_bracket='[', right_bracket=']')
        transformation_label = MathTex(r"\begin{pmatrix} 1 & 1 \\ 1 & 2 \end{pmatrix}").next_to(transformation_matrix, UP)

        # Create the transformed vector [6, 6]
        transformed_vector = Arrow(ORIGIN, [6, 6, 0], color=RED)
        transformed_label = MathTex(r"\begin{pmatrix} 6 \\ 6 \end{pmatrix}").next_to(transformed_vector, UP)

        # Add axes to the scene
        self.play(Create(axes))

        # Display the original vector and label
        self.play(Create(original_vector), Write(original_label))
        
        # Display the transformation matrix
        self.play(Create(transformation_matrix), Write(transformation_label))

        # Perform the transformation animation
        self.play(Transform(original_vector, transformed_vector), Transform(original_label, transformed_label))

        # Show the final transformed vector
        self.wait(2)
# To run this, use the command:
# manim -pql filename.py CartesianMatrixTransformation
class ReflectionExample(Scene):
    def construct(self):
        # Create axes
        axes = Axes(
            x_range=(-10, 10),
            y_range=(-10, 10),
            axis_config={"color": BLUE},
        )

        # Define the incident vector I and normal vector N
        incident_vector = np.array([1, -1, 0])
        normal_vector = np.array([-1, -2, 0])

        # Create arrows for the incident and normal vectors
        incident_arrow = Arrow(ORIGIN, incident_vector, color=YELLOW)
        normal_arrow = Arrow(ORIGIN, normal_vector, color=GREEN)

        # Calculate the reflection vector R
        dot_product = np.dot(incident_vector, normal_vector)
        reflection_vector = incident_vector - 2 * dot_product * (normal_vector / np.linalg.norm(normal_vector))
        
        # Create an arrow for the reflection vector
        reflection_arrow = Arrow(ORIGIN, reflection_vector, color=RED)

        # Add everything to the scene
        self.play(Create(axes))
        self.play(Create(incident_arrow), Create(normal_arrow))
        self.play(Create(reflection_arrow))

        # Add labels
        incident_label = MathTex(r"\mathbf{I}").next_to(incident_arrow, UP)
        normal_label = MathTex(r"\mathbf{N}").next_to(normal_arrow, LEFT)
        reflection_label = MathTex(r"\mathbf{R}").next_to(reflection_arrow, DOWN)

        self.play(Write(incident_label), Write(normal_label), Write(reflection_label))

        # Show the final frame
        self.wait(2)

class DotProductScene(Scene):
    def construct(self):
        # Create the Cartesian plane
        axes = Axes(
            x_range=[-5, 5, 1],
            y_range=[-5, 5, 1],
            axis_config={"color": GREY},
        )

        # Create vectors
        vector_a = Arrow(ORIGIN, np.array([3, 2, 0]), color=BLUE)
        vector_b = Arrow(ORIGIN, np.array([1, -1, 0]), color=RED)

        # Create labels for the vectors
        label_a = MathTex(r'\vec{a} = (9, 7)').next_to(vector_a, UP)
        label_b = MathTex(r'\vec{b} = (1, -1)').next_to(vector_b, DOWN)

        # Display the Cartesian plane and vectors
        self.play(Create(axes))
        self.play(Create(vector_a), Write(label_a))
        self.play(Create(vector_b), Write(label_b))
        
        # Calculate the dot product
        dot_product = 9 * 1 + 7 * (-1)  # 9*1 + 7*(-1) = 2
        dot_product_text = MathTex(r'\vec{a} \cdot \vec{b} = 9 \cdot 1 + 7 \cdot (-1) = 2').to_edge(DOWN)

        # Show the dot product calculation
        self.play(Write(dot_product_text))
        self.wait(2)

        # Highlight the result value
        result_value = MathTex("= 2").next_to(dot_product_text, RIGHT)
        self.play(Write(result_value))

        # Wait before ending the scene
        self.wait(2)

        # End scene
        self.play(FadeOut(vector_a), FadeOut(vector_b), FadeOut(label_a), FadeOut(label_b), FadeOut(dot_product_text), FadeOut(result_value), FadeOut(axes))
        
def axis(self, dimension=2, lim=10):
    if dimension == 2:
        axes = Axes(
            x_range=(-lim, lim),
            y_range=(-lim, lim),
            axis_config={"color": BLUE},
        )
    elif dimension == 3:
        axes = ThreeDAxes(
            x_range=(-lim, lim),
            y_range=(-lim, lim),
            z_range=(-lim, lim),
            axis_config={"color": BLUE},
        )
    else:
        raise ValueError("Dimension must be 2 or 3.")

    self.play(Create(axes))
    return axes
if __name__ == '__main__':
    anim = '' #input("Animation: ")
    if anim != '':
        anim = ' ' + anim
    subprocess.call(f"manim -pql manim-test.py{anim}")